"""V7.8 opponent-generalization distillation. Dry by default; never promotes."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v73_diagnostic as base
from scripts import draft_v76_distillation as v76
from scripts import resume_v76_verified as verified
from scripts.draft_ml_v7_run import lock, preflight
from scripts.draft_v77_stability import shifted_players
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_data import softmax, utility
from web.backend.services.draft_ml.v7_state import CATEGORIES, State, compatible, sha

CONFIG = ROOT / 'configs/draft_ml_v78.json'
OUTPUT = ROOT / 'artifacts/draft_ml/standard8-v78-generalization'
BASELINE = ROOT / 'artifacts/draft_ml/standard8-v76-distillation/training/best.pt'
OLD = ROOT / 'artifacts/draft_ml/standard8-v7/iteration-2/training/best.pt'
TRAIN_FAMILIES = ('legacy_strong', 'legacy_mixed', 'weighted', 'topk', 'specialist', 'diverse')
VALIDATION_CONDITIONS = ('familiar', 'proxy_need', 'projection_shift')
HOLDOUT_CONDITIONS = ('strong', 'mixed', 'unseen_need', 'unseen_hybrid', 'projection_shift')
POLICIES = None


def configuration():
    settings = json.loads(CONFIG.read_text(encoding='utf-8'))
    config = json.loads((ROOT / 'configs/draft_ml_v7.json').read_text(encoding='utf-8'))
    config.update(seed=settings['seed'], workers=settings['workers'], training=settings['training'])
    return config, settings, ROOT / settings['output']


def fingerprint():
    out = verified.install()
    old_journal = verified.check(out)
    config, settings, _ = configuration()
    digest = hashlib.sha256(json.dumps(dict(config=config, settings=settings, old_journal=old_journal), sort_keys=True).encode())
    dependencies = (
        Path(__file__), CONFIG, ROOT / 'scripts/resume_v76_verified.py',
        ROOT / 'scripts/run_v74_resilient.py', ROOT / 'scripts/draft_v77_stability.py',
        ROOT / 'scripts/draft_v73_diagnostic.py', ROOT / 'web/backend/services/draft_ml/v7_state.py',
        ROOT / 'web/backend/services/draft_ml/v7_data.py', ROOT / 'web/backend/services/draft_ml/v7_train.py',
        ROOT / 'web/backend/services/draft_ml/v7_network.py', ROOT / 'web/backend/services/draft_ml/evolution.py',
        ROOT / 'web/backend/services/draft_evaluation.py', ROOT / 'web/backend/services/draft_benchmark.py',
        ROOT / 'core/z_score.py', ROOT / 'core/projection.py',
    )
    for path in dependencies:
        digest.update(path.read_bytes())
    digest.update(sha(BASELINE).encode())
    return digest.hexdigest()


def initialize(checkpoint=None, evaluate=False):
    global POLICIES
    verified.install()
    config, settings, _ = configuration()
    base.initialize(config, settings)
    from web.backend.services.draft_ml.v7_network import NeuralPolicy
    baseline = NeuralPolicy(BASELINE)
    # Candidate generation must use V7.6, not the older arena.history[2].
    base.CTX[3].history.append(baseline)
    POLICIES = {'old': base.CTX[3].history[2], 'v76': baseline}
    if checkpoint:
        POLICIES['v78'] = NeuralPolicy(checkpoint)


def weighted_style(seed, specialist=False):
    rng = random.Random(seed)
    if specialist:
        focus = set(rng.sample(list(CATEGORIES), 3))
        weights = {category: (1.8 if category in focus else .25) for category in CATEGORIES}
    else:
        weights = {category: rng.uniform(.35, 1.65) for category in CATEGORIES}
        for category in rng.sample(list(CATEGORIES), rng.choice((0, 1, 2))):
            weights[category] = 0.0
    return {'kind': 'weighted', 'weights': weights}


def assignments(arena, family, seed):
    rng = random.Random(seed)
    if family in ('legacy_strong', 'legacy_mixed'):
        raw = base.assignments_for(arena, family.split('_', 1)[1], seed)
        return {slot: {'kind': 'legacy', 'policy': policy} for slot, policy in raw.items()}
    result = {}
    for slot in range(1, arena.config['team_count'] + 1):
        kind = family
        if family == 'diverse':
            kind = rng.choice(('weighted', 'topk', 'specialist'))
        if kind == 'topk':
            result[slot] = {'kind': 'topk', 'k': rng.choice((2, 3, 5, 7))}
        else:
            result[slot] = weighted_style(f'{seed}:{slot}', specialist=kind == 'specialist')
    return result


def need_weights(state):
    roster = state.context().roster
    totals = {category: sum(p.get('z_scores', {}).get(category, 0.0) for p in roster) for category in CATEGORIES}
    return {category: 1.0 / (1.0 + math.exp(max(-20.0, min(20.0, totals[category] / 3.0)))) for category in CATEGORIES}


def action_for(state, arena, policy, seed):
    kind = policy['kind']
    if kind == 'legacy':
        return arena.opponent_action(state, {state.slot: policy['policy']}, seed)
    if kind == 'topk':
        ranked = arena.order(state)[:policy['k']]
        return random.Random(f'{seed}:{state.pick}:{state.slot}').choice(ranked)[0]
    legal = state.legal()
    if kind == 'weighted':
        weights = policy['weights']
        return max(legal, key=lambda i: (sum(weights[c] * state.players[i].get('z_scores', {}).get(c, 0.0) for c in CATEGORIES), -i))
    if kind in ('proxy_need', 'sigmoid_need'):
        weights = need_weights(state)
        if kind == 'proxy_need':
            # Linear proxy deliberately differs from the held-out sigmoid rule.
            roster = state.context().roster
            totals = {c: sum(p.get('z_scores', {}).get(c, 0.0) for p in roster) for c in CATEGORIES}
            floor = min(totals.values(), default=0.0)
            weights = {c: 1.0 / (1.0 + max(0.0, totals[c] - floor)) for c in CATEGORIES}
        return max(legal, key=lambda i: (sum(weights[c] * state.players[i].get('z_scores', {}).get(c, 0.0) for c in CATEGORIES), -i))
    if kind == 'hybrid':
        ranked = [i for i, _ in arena.order(state)[:8]]
        weights = need_weights(state)
        roster = state.context().roster
        open_positions = [position for position in state.slots if not any(compatible(p, position) for p in roster)]
        def score(i):
            player = state.players[i]
            need = sum(weights[c] * player.get('z_scores', {}).get(c, 0.0) for c in CATEGORIES)
            scarcity = sum(compatible(player, position) for position in open_positions) / max(1, len(open_positions))
            return need + .4 * scarcity
        return max(ranked, key=lambda i: (score(i), -i))
    raise ValueError(f'Unknown opponent policy: {kind}')


def finish(state, hero, arena, opponents, seed, continuation):
    while not state.complete:
        if state.slot == hero:
            action = arena.order(state, continuation)[0][0]
        else:
            action = action_for(state, arena, opponents[state.slot], seed)
        state.apply(action)
    config = base.CTX[0]
    return state.targets(hero, seed, config['gp_stddev'], config['stat_stddev'])


def candidate_ids(state, arena, settings):
    baseline = [i for i, _ in arena.order(state, POLICIES['v76'])]
    teacher = [i for i, _ in arena.order(state)]
    pools = [baseline[:4], teacher[:4]]
    for anchor in arena.anchors[:4]:
        pools.append([state.teacher_scores([anchor])[0][0]])
    weakest = sorted(CATEGORIES, key=lambda c: sum(p.get('z_scores', {}).get(c, 0.0) for p in state.context().roster))[:2]
    for category in weakest:
        pools.append([max(state.legal(), key=lambda i: state.players[i].get('z_scores', {}).get(category, 0.0))])
    return list(dict.fromkeys(i for pool in pools for i in pool))[:settings['large_candidates']]


def blind_prior(arena, key, rollout):
    family = random.Random(f'{key}:family:{rollout}').choice(TRAIN_FAMILIES)
    return assignments(arena, family, f'{key}:opponents:{rollout}')


def improved_target(state, hero, arena, settings, key):
    logits, _ = POLICIES['v76'].predict(state)
    legal = state.legal()
    baseline_policy = np.zeros(len(state.players), dtype=np.float32)
    baseline_policy[legal] = softmax(logits[legal], settings['teacher_temperature'])
    baseline_action = max(legal, key=lambda i: float(logits[i]))
    ids = candidate_ids(state, arena, settings)
    selected = {}
    for candidate in ids:
        selected[candidate] = []
        for rollout in range(settings['large_rollouts']):
            branch = state.clone(); branch.apply(candidate)
            selected[candidate].append(finish(branch, hero, arena, blind_prior(arena, key, rollout), f'{key}:select:{rollout}', POLICIES['v76']))
    chosen = base.choose(ids, selected)
    audit = {}
    for candidate in set((baseline_action, chosen)):
        samples = []
        for rollout in range(settings['audit_rollouts']):
            branch = state.clone(); branch.apply(candidate)
            samples.append(finish(branch, hero, arena, blind_prior(arena, key + ':audit', rollout), f'{key}:audit:{rollout}', POLICIES['v76']))
        audit[candidate] = float(np.mean([utility(row) for row in samples]))
    gain = audit[chosen] - audit[baseline_action]
    accepted = chosen != baseline_action and gain >= settings['audit_min_utility_gain']
    target = baseline_policy.copy()
    if accepted:
        searched = np.zeros_like(target)
        searched[ids] = softmax([utility(np.mean(selected[i], axis=0)) for i in ids], settings['search_temperature'])
        blend = settings['baseline_policy_blend']
        target = blend * baseline_policy + (1.0 - blend) * searched
    return target, chosen if accepted else baseline_action, {'accepted': accepted, 'gain': gain, 'baseline': baseline_action, 'chosen': chosen}


def scenario(split, index):
    return f'v78:{configuration()[1]["seed"]}:{split}:{index}'


def generate_episode(job):
    split, index, path, provenance = job
    config, settings, payload, arena = base.CTX
    key = scenario(split, index)
    hero = index % config['team_count'] + 1
    family = TRAIN_FAMILIES[(index // config['team_count']) % len(TRAIN_FAMILIES)]
    opponents = assignments(arena, family, key)
    state = State(payload['players'], payload['roster_slots'], config['team_count'], config['rounds'])
    encodings, policies, audits = [], [], []
    while not state.complete:
        if state.slot != hero:
            state.apply(action_for(state, arena, opponents[state.slot], key + ':actual'))
            continue
        encoded = state.encode()
        logits, _ = POLICIES['v76'].predict(state)
        legal = state.legal()
        target = np.zeros(len(state.players), dtype=np.float32)
        target[legal] = softmax(logits[legal], settings['teacher_temperature'])
        action = max(legal, key=lambda i: float(logits[i]))
        if len(state.rosters[hero]) >= config['rounds'] - settings['late_picks']:
            target, action, audit = improved_target(state, hero, arena, settings, f'{key}:pick:{state.pick}')
            audits.append(audit)
        encodings.append(encoded); policies.append(target); state.apply(action)
    targets = np.mean([state.targets(hero, f'{key}:terminal:{i}', config['gp_stddev'], config['stat_stddev']) for i in range(settings['terminal_draws'])], axis=0)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('wb') as handle:
        np.savez_compressed(handle, tokens=np.stack([e[0] for e in encodings]), roles=np.stack([e[1] for e in encodings]),
            global_state=np.stack([e[2] for e in encodings]), legal=np.stack([e[3] for e in encodings]),
            loss_mask=np.stack([e[3] for e in encodings]), policy=np.stack(policies),
            value=np.repeat(targets[None], len(policies), axis=0), scenario=np.asarray(key), provenance=np.asarray(provenance),
            family=np.asarray(family), audits=np.asarray(json.dumps(audits)))
    v76.replace_retry(temp, path)
    return {'split': split, 'index': index, 'accepted': sum(row['accepted'] for row in audits), 'searched': len(audits)}


def evaluation_opponents(arena, split, condition, key, index):
    if condition in ('strong', 'mixed'):
        return assignments(arena, 'legacy_' + condition, key)
    if condition == 'familiar':
        return assignments(arena, 'legacy_' + ('strong' if index % 2 == 0 else 'mixed'), key)
    kind = {'proxy_need': 'proxy_need', 'unseen_need': 'sigmoid_need', 'unseen_hybrid': 'hybrid',
            'projection_shift': 'legacy'}[condition]
    if kind == 'legacy':
        return assignments(arena, 'legacy_mixed', key)
    return {slot: {'kind': kind} for slot in range(1, arena.config['team_count'] + 1)}


def evaluate_episode(job):
    split, condition, index = job
    config, settings, payload, arena = base.CTX
    key = f'v78:{settings["seed"]}:evaluation:{split}:{condition}:{index}'
    hero = index % config['team_count'] + 1
    players = shifted_players(payload['players'], key + ':inputs') if condition == 'projection_shift' else payload['players']
    opponents = evaluation_opponents(arena, split, condition, key, index)
    results = {}
    for mode, policy in POLICIES.items():
        state = State(players, payload['roster_slots'], config['team_count'], config['rounds'])
        while not state.complete:
            action = arena.order(state, policy)[0][0] if state.slot == hero else action_for(state, arena, opponents[state.slot], key + ':actual')
            state.apply(action)
        results[mode] = np.mean([state.targets(hero, f'{key}:terminal:{i}', config['gp_stddev'], config['stat_stddev']) for i in range(settings['terminal_draws'])], axis=0).tolist()
    return {'split': split, 'condition': condition, 'episode': index, 'scenario': key, 'results': results}


def comparison(rows, left, right, z=1.96):
    a = np.asarray([row['results'][left] for row in rows])
    b = np.asarray([row['results'][right] for row in rows])
    values = {'categories': a[:, :8].sum(1) - b[:, :8].sum(1), 'rank_gain': 9 * (b[:, 8] - a[:, 8]),
              'top4': a[:, 9] - b[:, 9], 'top1': a[:, 10] - b[:, 10]}
    result = {}
    for name, value in values.items():
        mean = float(value.mean()); margin = float(z * value.std(ddof=1) / np.sqrt(len(value)))
        result[name] = {'delta': mean, 'interval': [mean - margin, mean + margin], 'n_drafts': len(value)}
    return result


def report(rows, split):
    conditions = sorted({row['condition'] for row in rows})
    generalization_names = ('proxy_need',) if split == 'validation' else ('unseen_need', 'unseen_hybrid')
    generalization = [row for row in rows if row['condition'] in generalization_names]
    familiar_names = ('familiar',) if split == 'validation' else ('strong', 'mixed')
    familiar = [row for row in rows if row['condition'] in familiar_names]
    return {
        'primary': {
            'generalization_v78_vs_v76': comparison(generalization, 'v78', 'v76', 2.2414027276),
            'familiar_v78_vs_v76': comparison(familiar, 'v78', 'v76', 2.2414027276),
        },
        'pooled': {'v78_vs_v76': comparison(rows, 'v78', 'v76'), 'v78_vs_old': comparison(rows, 'v78', 'old')},
        'by_condition': {name: {'v78_vs_v76': comparison([r for r in rows if r['condition'] == name], 'v78', 'v76'),
                               'v78_vs_old': comparison([r for r in rows if r['condition'] == name], 'v78', 'old')} for name in conditions},
        'n_drafts': len(rows),
        'limitations': ['One frozen historical 8-cat/10-team player snapshot; not a new NBA season.',
                        'Synthetic opponents expand coverage but cannot represent every human draft strategy.',
                        'Training and validation use disjoint scenario seeds; final holdout uses two opponent rules absent from training and validation.',
                        'Two primary category contrasts use 97.5% Bonferroni intervals; other metrics are exploratory.'],
    }


def parallel(config, settings, jobs, worker, consume, out, stage, checkpoint=None):
    started = time.monotonic(); completed = 0
    with ProcessPoolExecutor(max_workers=settings['workers'], initializer=initialize, initargs=(checkpoint, checkpoint is not None)) as pool:
        pending = {pool.submit(worker, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                consume(future.result()); completed += 1
            elapsed = time.monotonic() - started
            save(out / 'stage-progress.json', {'stage': stage, 'completed': completed, 'total': len(jobs),
                'elapsed_seconds': elapsed, 'eta_seconds': elapsed / completed * (len(jobs) - completed) if completed else None})


def phase(name, expected):
    if fingerprint() != expected:
        raise ValueError('Stage code/input mismatch')
    config, settings, out = configuration()
    if name == 'generate':
        jobs = []
        for split, count in settings['episodes'].items():
            for index in range(count):
                path = out / 'data' / split / f'{index:06d}.npz'
                if path.exists():
                    with np.load(path, allow_pickle=False) as data:
                        if str(data['provenance']) != expected or str(data['scenario']) != scenario(split, index):
                            raise ValueError(f'Saved data mismatch: {path}')
                else:
                    jobs.append((split, index, str(path), expected))
        parallel(config, settings, jobs, generate_episode, lambda row: None, out, name)
        accepted = searched = training_accepted = 0
        families = {}
        for path in (out / 'data').glob('*/*.npz'):
            with np.load(path, allow_pickle=False) as data:
                audits = json.loads(str(data['audits'])); family = str(data['family'])
                accepted += sum(row['accepted'] for row in audits); searched += len(audits)
                families[family] = families.get(family, 0) + 1
                if path.parent.name == 'train':
                    training_accepted += sum(row['accepted'] for row in audits)
        save(out / 'data/complete.json', {'provenance': expected, 'accepted': accepted, 'searched': searched,
            'training_accepted': training_accepted, 'families': families})
    elif name == 'train':
        from web.backend.services.draft_ml import v7_train as training
        training.atomic_json = save
        original = training.atomic_torch
        def checkpoint_write(path, payload):
            for attempt in range(21):
                try:
                    original(path, payload); return
                except PermissionError:
                    if attempt == 20: raise
                    time.sleep(.5)
        training.atomic_torch = checkpoint_write
        training.fit(config, out / 'data', out / 'training', expected, warm_start=BASELINE)
    else:
        split = name
        conditions = VALIDATION_CONDITIONS if split == 'validation' else HOLDOUT_CONDITIONS
        count = settings['evaluation'][split + '_per_condition']
        rows, jobs = [], []
        for condition in conditions:
            for index in range(count):
                path = out / split / f'{condition}-{index:04d}.json'
                if path.exists():
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if row['provenance'] != expected or row['checkpoint_sha256'] != sha(out / 'training/best.pt'):
                        raise ValueError(f'Evaluation mismatch: {path}')
                    rows.append(row)
                else:
                    jobs.append((split, condition, index))
        def consume(row):
            row.update(provenance=expected, checkpoint_sha256=sha(out / 'training/best.pt')); rows.append(row)
            save(out / split / f"{row['condition']}-{row['episode']:04d}.json", row)
        parallel(config, settings, jobs, evaluate_episode, consume, out, name, str(out / 'training/best.pt'))
        rows.sort(key=lambda row: (row['condition'], row['episode']))
        save(out / split / 'summary.json', {**report(rows, split), 'provenance': expected,
            'checkpoint_sha256': sha(out / 'training/best.pt')})


def plan():
    config, settings, out = configuration()
    audit = preflight(config, hardware=True)
    if OUTPUT != out:
        raise ValueError('Output constant/config mismatch')
    if not BASELINE.exists() or not OLD.exists():
        raise ValueError('Missing frozen baseline checkpoint')
    if set(TRAIN_FAMILIES) & set(VALIDATION_CONDITIONS + HOLDOUT_CONDITIONS):
        raise ValueError('Opponent-family leakage by name')
    if any(value <= 0 or value % config['team_count'] for value in settings['episodes'].values()):
        raise ValueError('Episode counts must balance all draft seats')
    for value in settings['evaluation'].values():
        if value <= 0 or value % config['team_count']:
            raise ValueError('Evaluation counts must balance all draft seats')
    generated = sum(settings['episodes'].values())
    evaluated = len(VALIDATION_CONDITIONS) * settings['evaluation']['validation_per_condition'] + len(HOLDOUT_CONDITIONS) * settings['evaluation']['holdout_per_condition']
    return {'status': 'PREPARED_NOT_STARTED', 'audit': audit, 'settings': settings, 'output': str(out),
        'training_families': list(TRAIN_FAMILIES), 'validation_conditions': list(VALIDATION_CONDITIONS),
        'holdout_conditions': list(HOLDOUT_CONDITIONS), 'data_drafts': generated,
        'searched_late_decisions': generated * settings['late_picks'], 'evaluation_drafts': evaluated,
        'hours': {'generation': [13.5, 16.5], 'training': [.3, 1.0], 'validation_and_holdout': [.7, 1.5], 'total': [14.5, 19.0]},
        'estimate_basis': 'V7.6 generated 480 drafts in about 9.55 h; V7.8 generates 720 at the same 12x8 plus independent 4-rollout audit budget. Evaluation is calibrated from V7.7.',
        'resume': 'completed episode, epoch and evaluation scenario', 'auto_promote': False,
        'stopping': 'Validation gate, then one frozen holdout. Always stop for user review before universal architecture.'}


def run():
    prepared = plan(); digest = fingerprint(); config, settings, out = configuration()
    out.mkdir(parents=True, exist_ok=True)
    with lock(out / 'run.lock'):
        journal_path = out / 'run-state.json'
        journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'provenance': digest, 'completed': [], 'checksums': {}}
        if journal['provenance'] != digest:
            raise ValueError('Incompatible resume; preserve old output and use a new directory')
        save(out / 'plan.json', prepared)
        def status(phase_name, error=None):
            save(out / 'status.json', {'pid': os.getpid(), 'phase': phase_name, 'completed': len(journal['completed']),
                'total': 4, 'provenance': digest, 'error': error, 'updated_at': time.time(), 'training': True})
        def checks(stage):
            if stage == 'generate': paths = [*sorted((out / 'data').glob('*/*.npz')), out / 'data/complete.json']
            elif stage == 'train': paths = [out / 'training/best.pt', out / 'training/complete.json']
            else: paths = [out / stage / 'summary.json']
            return {str(path.relative_to(out)): sha(path) for path in paths}
        try:
            for stage in ('generate', 'train', 'validation', 'holdout'):
                if stage == 'train':
                    generated = json.loads((out / 'data/complete.json').read_text())
                    if generated['training_accepted'] < settings['minimum_accepted_training_picks']:
                        save(out / 'gate.json', {'passed': False, 'reason': 'Too few accepted search improvements',
                            'training_accepted': generated['training_accepted']}); status('STOP_FOR_REVIEW'); return
                if stage == 'holdout':
                    validation = json.loads((out / 'validation/summary.json').read_text())
                    familiar = validation['primary']['familiar_v78_vs_v76']['categories']['delta']
                    generalization = validation['primary']['generalization_v78_vs_v76']['categories']['delta']
                    if familiar < -.05 or generalization < -.03:
                        save(out / 'gate.json', {'passed': False, 'reason': 'Validation regression; holdout remains unopened',
                            'familiar_delta': familiar, 'generalization_delta': generalization}); status('STOP_FOR_REVIEW'); return
                    frozen = {'checkpoint_sha256': sha(out / 'training/best.pt'), 'provenance': digest}
                    if (out / 'frozen.json').exists() and json.loads((out / 'frozen.json').read_text()) != frozen:
                        raise ValueError('Frozen checkpoint changed')
                    save(out / 'frozen.json', frozen)
                if stage in journal['completed']:
                    if checks(stage) != journal['checksums'][stage]:
                        raise ValueError(f'Completed output changed: {stage}')
                    continue
                status('RUNNING:' + stage)
                with (out / f'{stage}.log').open('a', encoding='utf-8') as handle:
                    child = subprocess.Popen([sys.executable, '-u', str(Path(__file__)), '--stage', stage, '--provenance', digest],
                        cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
                    try:
                        while child.poll() is None:
                            try: child.wait(timeout=15)
                            except subprocess.TimeoutExpired: status('RUNNING:' + stage)
                    except BaseException:
                        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True); raise
                if child.returncode:
                    raise RuntimeError(f'{stage} failed; saved progress retained')
                journal['completed'].append(stage); journal['checksums'][stage] = checks(stage); save(journal_path, journal)
            holdout = json.loads((out / 'holdout/summary.json').read_text())
            save(out / 'summary.json', {'provenance': digest, 'holdout': holdout,
                'decision': 'STOP_FOR_USER_REVIEW_NO_PROMOTION'})
            status('COMPLETE')
        except BaseException:
            status('FAILED', traceback.format_exc()); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stage', choices=('generate', 'train', 'validation', 'holdout'))
    parser.add_argument('--provenance')
    args = parser.parse_args()
    if args.stage:
        phase(args.stage, args.provenance)
    elif args.execute:
        run()
    else:
        print(json.dumps(plan(), indent=2))
