"""Episode-sharded imitation and counterfactual data, with disjoint split seeds."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import random

import numpy as np

from .evolution import EvolutionConfig, fixed_anchor_population
from .v7_state import State, unique_teacher, CATEGORIES, validate_snapshot


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def scenario_seed(config, split, iteration, episode):
    return f"v7:{config['seed']}:{split}:{iteration}:{episode}"


def softmax(values, temperature):
    x = np.asarray(values, dtype=np.float64) / temperature
    x -= x.max()
    exp = np.exp(x)
    return (exp / exp.sum()).astype(np.float32)


def utility(target):
    # Identical precommitted objective for all V7 search arms.
    return float(target[:8].sum() - .08 * target[8] * 9 + .35 * target[9] + .20 * target[10])


class Arena:
    def __init__(self, config, teacher):
        self.config = config
        self.teacher = unique_teacher(teacher)
        self.anchors = fixed_anchor_population(CATEGORIES, EvolutionConfig(anchor_pool_size=40, seed=config['seed'] + 191))
        self.history = []

    def opponents(self, seed):
        rng = random.Random(seed)
        result = {}
        for slot in range(1, self.config['team_count'] + 1):
            if self.history and rng.random() < .15:
                result[slot] = rng.randrange(len(self.history))
            else:
                result[slot] = self.teacher if rng.random() < .25 else [rng.choice(self.anchors)]
        return result

    def opponent_action(self, state, assignments, seed):
        if isinstance(assignments[state.slot], int):
            return self.order(state, self.history[assignments[state.slot]])[0][0]
        ranked = state.teacher_scores(assignments[state.slot])
        # Randomness keyed by overall pick AND player: shared counterfactual draws.
        return max(ranked, key=lambda pair: pair[1] + random.Random(f'{seed}:{state.pick}:{pair[0]}').gauss(0, .035))[0]

    def order(self, state, neural=None):
        legal = state.legal()
        if neural is None:
            return state.teacher_scores(self.teacher, legal)
        logits, _ = neural.predict(state, legal)
        return sorted(((i, float(logits[i])) for i in legal), key=lambda x: (-x[1], x[0]))

    def finish(self, state, hero, assignments, seed, continuation=None, value_horizon=0):
        own_turns = 0
        while not state.complete:
            if state.slot == hero:
                own_turns += 1
                if continuation is not None and value_horizon and own_turns >= value_horizon:
                    # Bootstrap only at our next decision, matching the value training perspective.
                    return continuation.predict(state)[1]
                action = self.order(state, continuation)[0][0]
            else:
                action = self.opponent_action(state, assignments, seed)
            state.apply(action)
        return state.targets(hero, seed, self.config['gp_stddev'], self.config['stat_stddev'])

    def search(self, state, hero, seed, proposal=None, continuation=None, value_horizon=0):
        budget = self.config['search']
        ordered = self.order(state, proposal)
        candidate_ids = [i for i, _ in ordered[:budget['candidates']]]
        outcomes = []
        for candidate in candidate_ids:
            samples = []
            for rollout in range(budget['rollouts']):
                rollout_seed = f'{seed}:rollout:{rollout}'
                branch = state.clone()
                branch.apply(candidate)
                assignments = self.opponents(rollout_seed)
                samples.append(self.finish(branch, hero, assignments, rollout_seed, continuation, value_horizon))
            outcomes.append(np.mean(samples, axis=0))
        utilities = [utility(row) for row in outcomes]
        weights = softmax(utilities, budget['temperature'])
        return candidate_ids, weights, np.asarray(outcomes), utilities


_WORKER = None


def initialize_worker(config, snapshot_path, teacher_path, checkpoint, training_history=False, arena_offset=0):
    global _WORKER
    snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    teacher = json.loads(Path(teacher_path).read_text(encoding='utf-8'))
    neural = None
    if checkpoint:
        import torch
        torch.set_num_threads(1)
        from .v7_network import NeuralPolicy
        neural = NeuralPolicy(checkpoint)
    arena = Arena({**config, 'seed': config['seed'] + arena_offset}, teacher)
    if training_history and checkpoint:
        root = Path(checkpoint).parents[2]
        latest_iteration = int(Path(checkpoint).parents[1].name.split('-')[-1])
        for iteration in range(latest_iteration + 1):
            previous = root / f'iteration-{iteration}/training/best.pt'
            if previous.is_file():
                arena.history.append(NeuralPolicy(previous))
    _WORKER = config, snapshot, arena, neural


def generate_episode(job):
    split, iteration, episode, path, provenance = job
    config, snapshot, arena, neural = _WORKER
    seed = scenario_seed(config, split, iteration, episode)
    rng = random.Random(seed)
    hero = episode % config['team_count'] + 1
    state = State(snapshot['players'], snapshot['roster_slots'], config['team_count'], config['rounds'])
    assignments = arena.opponents(seed)
    search_rounds = set(rng.sample(range(config['rounds']), min(config['rounds'], config['search']['states_per_episode']))) if iteration else set()
    records = []
    targets_policy, loss_masks = [], []
    while not state.complete:
        if state.slot != hero:
            state.apply(arena.opponent_action(state, assignments, seed))
            continue
        legal = state.legal()
        encoded = state.encode(legal)
        ranked = arena.order(state, neural)
        pi = np.zeros(len(state.players), dtype=np.float32)
        loss_mask = encoded[3].copy()
        if len(state.rosters[hero]) in search_rounds:
            ids, probabilities, _, _ = arena.search(state, hero, f'{seed}:pick:{state.pick}', neural, neural)
            pi[ids] = probabilities
            loss_mask[:] = False
            loss_mask[ids] = True
            action = ids[int(np.argmax(probabilities))]
        else:
            pi[[i for i, _ in ranked]] = softmax([score for _, score in ranked], .08 if neural is None else 1.0)
            action = ranked[0][0]
            if split == 'train' and rng.random() < .1:
                action = rng.choice(ranked[:min(8, len(ranked))])[0]
        records.append(encoded)
        targets_policy.append(pi)
        loss_masks.append(loss_mask)
        state.apply(action)
    values = state.targets(hero, f'{seed}:terminal', config['gp_stddev'], config['stat_stddev'])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as handle:
        np.savez_compressed(handle,
            tokens=np.stack([r[0] for r in records]), roles=np.stack([r[1] for r in records]),
            global_state=np.stack([r[2] for r in records]), legal=np.stack([r[3] for r in records]),
            loss_mask=np.stack(loss_masks), policy=np.stack(targets_policy),
            value=np.repeat(values[None], len(records), axis=0),
            scenario=np.asarray(seed), provenance=np.asarray(provenance))
    os.replace(temporary, path)
    return len(records)


def generate(config, snapshot, teacher, output, iteration, provenance, checkpoint=None):
    output = Path(output)
    counts = config['episodes'] if iteration == 0 else config['improvement_episodes']
    jobs = []
    for split, episodes in counts.items():
        for episode in range(episodes):
            path = output / split / f'{episode:06d}.npz'
            if path.exists():
                with np.load(path, allow_pickle=False) as saved:
                    if str(saved['provenance']) != provenance or str(saved['scenario']) != scenario_seed(config, split, iteration, episode):
                        raise ValueError(f'Incompatible episode {path}')
                continue
            jobs.append((split, iteration, episode, str(path), provenance))
    with ProcessPoolExecutor(max_workers=config['workers'], initializer=initialize_worker, initargs=(config, str(snapshot), str(teacher), str(checkpoint) if checkpoint else None, True)) as pool:
        futures = {pool.submit(generate_episode, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            records = future.result()
            print(f'episode {index}/{len(jobs)} saved ({records} states)', flush=True)
    atomic_json(output / 'complete.json', {'iteration': iteration, 'counts': counts, 'provenance': provenance})
