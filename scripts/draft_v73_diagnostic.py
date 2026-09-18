"""Read-only model diagnostic. Never trains or promotes a checkpoint."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from web.backend.services.draft_ml.v7_data import Arena, atomic_json, utility
from web.backend.services.draft_ml.v7_state import State, CATEGORIES, sha
from scripts.draft_ml_v7_run import lock, preflight, fingerprint

OUTPUT = ROOT / 'artifacts/draft_ml/standard8-v73-diagnostic'
SETTINGS = dict(episodes_per_arena=30, workers=6, rounds_sampled=[1, 6, 11],
                small_candidates=4, small_rollouts=3, large_candidates=12,
                large_rollouts=8, audit_rollouts=8, seed=730908)
ARENAS = ('strong', 'strategic', 'mixed')
CTX = None


def initialize(config, settings):
    global CTX
    import torch
    torch.set_num_threads(1)
    from web.backend.services.draft_ml.v7_network import NeuralPolicy
    payload = json.loads((ROOT / config['snapshot']).read_text())
    genomes = json.loads((ROOT / config['teacher'] / 'genomes.json').read_text())
    arena = Arena(config, genomes)
    arena.history = [NeuralPolicy(ROOT / f'artifacts/draft_ml/standard8-v7/iteration-{i}/training/best.pt') for i in range(3)]
    CTX = config, settings, payload, arena


def assignments_for(arena, name, seed):
    rng = random.Random(seed)
    punts = [x for x in arena.anchors if 'punt' in x['id'] or 'specialist' in x['id']]
    result = {}
    for slot in range(1, arena.config['team_count'] + 1):
        if name == 'strong':
            result[slot] = rng.choice([arena.teacher, *[[g] for g in arena.teacher], 0, 1, 2])
        elif name == 'strategic':
            result[slot] = [rng.choice(punts)] if slot % 2 else arena.teacher
        elif name == 'mixed':
            result[slot] = rng.choice([arena.teacher, 0, 1, 2, [rng.choice(arena.anchors)]])
        else:
            raise ValueError(name)
    return result


def candidates(state, arena, settings):
    teacher = [i for i, _ in arena.order(state)]
    student = [i for i, _ in arena.order(state, arena.history[2])]
    # Preserve both small-search pools, then add strategy and team-need alternatives.
    pools = [teacher[:4], student[:4]]
    for anchor in arena.anchors[:4]:
        pools.append([state.teacher_scores([anchor])[0][0]])
    ctx = state.context()
    weakest = sorted(CATEGORIES, key=lambda c: sum(p.get('z_scores', {}).get(c, 0) for p in ctx.roster))[:2]
    for category in weakest:
        pools.insert(2, [max(teacher, key=lambda i: state.players[i].get('z_scores', {}).get(category, 0))])
    expanded = list(dict.fromkeys(i for pool in pools for i in pool))[:settings['large_candidates']]
    return teacher[:settings['small_candidates']], student[:settings['small_candidates']], expanded


def choose(ids, outcomes):
    return max(ids, key=lambda i: (utility(np.mean(outcomes[i], axis=0)), -i))


def summarize(rows):
    from web.backend.services.draft_benchmark import _ci95
    def metric(values):
        return dict(delta=float(np.mean(values)), ci95=_ci95(values), n_drafts=len(values))
    result = {}
    for name in ARENAS:
        group = [r for r in rows if r['arena'] == name]
        if not group:
            continue
        baseline = {}
        for mode in ('teacher', 'student'):
            targets = np.array([r['baseline'][mode] for r in group])
            baseline[mode] = dict(categories=float(targets[:, :8].sum(1).mean()),
                                  rank=float(1 + 9 * targets[:, 8].mean()),
                                  top4=float(targets[:, 9].mean()), top1=float(targets[:, 10].mean()))
        comparisons = {}
        for mode in ('student', 'small_teacher', 'small_student', 'expanded'):
            # The entire draft is the independent unit, NOT each rollout or decision.
            comparisons[mode + '_vs_teacher'] = metric([
                np.mean([sum(s['audit'][mode][:8]) - sum(s['audit']['teacher'][:8]) for s in r['states']]) for r in group])
        stages = {}
        for index, label in enumerate(('early', 'middle', 'late')):
            stages[label] = {mode: metric([sum(r['states'][index]['audit'][mode][:8]) - sum(r['states'][index]['audit']['teacher'][:8]) for r in group]) for mode in ('student', 'small_teacher', 'small_student', 'expanded')}
        result[name] = dict(baseline=baseline, local_action_comparisons=comparisons, by_stage=stages,
                            full_draft_student_vs_teacher=metric([sum(r['baseline']['student'][:8])-sum(r['baseline']['teacher'][:8]) for r in group]))
    return dict(arenas=result, decision='STOP_FOR_USER_REVIEW_NO_TRAINING', limitations=[
        'Exploratory diagnostic, not independent final confirmation. 30 drafts per arena is a pilot-sized sample.',
        'Local action benefit uses a common V6.3 continuation, not a full search policy draft.',
        'Opponent policy identities are fixed and known in simulated branches; this is an optimistic search-capability test.',
        'Strategic anchors are category-biased synthetic policies, not proven optimal human punt strategies.',
        'Same historical 8-cat, 10-team snapshot. No new-season generalization claim.',
        'Multiple exploratory comparisons; intervals are unadjusted. Use fresh confirmation before strength claims.'])


def episode(job):
    name, index = job
    config, settings, payload, arena = CTX
    seed = f"v73:{settings['seed']}:{name}:{index}"
    hero = index % config['team_count'] + 1
    assignments = assignments_for(arena, name, seed)
    state = State(payload['players'], payload['roster_slots'], config['team_count'], config['rounds'])
    baseline = {}
    for mode, policy in (('teacher', None), ('student', arena.history[2])):
        baseline[mode] = arena.finish(state.clone(), hero, assignments, seed, policy).tolist()
    records = []
    while not state.complete:
        if state.slot != hero:
            state.apply(arena.opponent_action(state, assignments, seed))
            continue
        round_index = len(state.rosters[hero])
        if round_index in settings['rounds_sampled']:
            small_t, small_s, expanded = candidates(state, arena, settings)
            ids = list(dict.fromkeys([*small_t, *small_s, *expanded]))
            selection = {}
            for candidate in ids:
                selection[candidate] = []
                for rollout in range(settings['large_rollouts']):
                    branch = state.clone(); branch.apply(candidate)
                    selection[candidate].append(arena.finish(branch, hero, assignments, f'{seed}:select:{round_index}:{rollout}'))
            short = {i: samples[:settings['small_rollouts']] for i, samples in selection.items()}
            actions = dict(teacher=small_t[0], student=small_s[0], small_teacher=choose(small_t, short),
                           small_student=choose(small_s, short), expanded=choose(expanded, selection))
            audited = {}
            for candidate in set(actions.values()):
                samples = []
                for rollout in range(settings['audit_rollouts']):
                    branch = state.clone(); branch.apply(candidate)
                    samples.append(arena.finish(branch, hero, assignments, f'{seed}:audit:{round_index}:{rollout}'))
                audited[candidate] = np.mean(samples, axis=0).tolist()
            records.append(dict(round=round_index+1, actions=actions, candidates=ids,
                                audit={m: audited[i] for m, i in actions.items()}))
        # Alternate prefix policies by whole draft to avoid only teacher-state coverage.
        state.apply(arena.order(state, arena.history[2] if index % 2 else None)[0][0])
    return dict(arena=name, episode=index, scenario=seed, baseline=baseline, states=records)


def digest(config, settings):
    h = hashlib.sha256((fingerprint(config) + json.dumps(settings, sort_keys=True)).encode())
    h.update(Path(__file__).read_bytes())
    for i in range(3):
        h.update(sha(ROOT / f'artifacts/draft_ml/standard8-v7/iteration-{i}/training/best.pt').encode())
    return h.hexdigest()


def run(pilot=False):
    config = json.loads((ROOT / 'configs/draft_ml_v7.json').read_text())
    preflight(config)
    settings = dict(SETTINGS)
    out = OUTPUT / 'pilot' if pilot else OUTPUT
    if pilot:
        settings['episodes_per_arena'] = 2
    provenance = digest(config, settings)
    out.mkdir(parents=True, exist_ok=True)
    with lock(out / 'run.lock'):
        status_file = out / 'status.json'
        if status_file.exists() and json.loads(status_file.read_text())['provenance'] != provenance:
            raise ValueError('Changed code/config/checkpoint: preserve old run and use new output')
        jobs, rows = [], []
        for name in ARENAS:
            for index in range(settings['episodes_per_arena']):
                path = out / 'episodes' / f'{name}-{index:04d}.json'
                if path.exists():
                    row = json.loads(path.read_text())
                    if row['provenance'] != provenance:
                        raise ValueError('Episode provenance mismatch')
                    rows.append(row)
                else:
                    jobs.append((name, index))
        started = time.monotonic()
        existing = len(rows)
        def status(phase, error=None):
            elapsed = time.monotonic() - started
            done = len(rows) - existing
            eta = elapsed / done * (len(jobs)-done) if done else None
            atomic_json(status_file, dict(phase=phase, completed=len(rows), total=3*settings['episodes_per_arena'],
                elapsed_seconds=elapsed, eta_seconds=eta, provenance=provenance, error=error,
                updated_at=time.time(), training=False))
        status('RUNNING')
        try:
            with ProcessPoolExecutor(max_workers=settings['workers'], initializer=initialize, initargs=(config, settings)) as pool:
                pending = {pool.submit(episode, job) for job in jobs}
                while pending:
                    ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
                    for future in ready:
                        row = future.result(); row['provenance'] = provenance
                        atomic_json(out / 'episodes' / f"{row['arena']}-{row['episode']:04d}.json", row)
                        rows.append(row)
                    status('RUNNING')
            rows.sort(key=lambda r: (r['arena'], r['episode']))
            atomic_json(out / 'summary.json', {**summarize(rows), 'provenance': provenance,
                        'settings': settings, 'elapsed_seconds': time.monotonic()-started})
            status('COMPLETE_DIAGNOSTIC_ONLY')
        except BaseException:
            status('FAILED', traceback.format_exc())
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--wait-pilot', action='store_true')
    args = parser.parse_args()
    if args.execute:
        if args.wait_pilot:
            # Wait inside the detached worker, never in the console viewer.
            deadline = time.monotonic() + 6 * 3600
            while True:
                pilot_status = json.loads((OUTPUT / 'pilot/status.json').read_text())
                if pilot_status['phase'] == 'COMPLETE_DIAGNOSTIC_ONLY':
                    break
                if pilot_status['phase'] == 'FAILED' or time.time() - pilot_status['updated_at'] > 180:
                    raise RuntimeError('Pilot failed or stopped updating; main diagnostic not started')
                if time.monotonic() > deadline:
                    raise RuntimeError('Pilot wait timeout; main diagnostic not started')
                time.sleep(15)
        run(args.pilot)
    else:
        print(json.dumps(SETTINGS, indent=2))
