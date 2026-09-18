"""V8.1 multi-format curriculum, validation gate and frozen holdout."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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

from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_data import softmax
from web.backend.services.draft_ml.v7_state import sha
from web.backend.services.draft_ml.v8_network import UniversalPolicy
from web.backend.services.draft_ml.v8_state import (CATEGORY_VOCAB, POSITIONS, UniversalState,
    compatible, normalize_categories, prepare_players)

CONFIG = ROOT / 'configs/draft_ml_v81.json'
OUTPUT = ROOT / 'artifacts/draft_ml/v81-multiformat'
OPPONENT_STYLES = ('balanced', 'weighted', 'punt', 'need', 'topk', 'specialist')
CTX = None
PLAYER_CACHE = {}


def configuration():
    settings = json.loads(CONFIG.read_text(encoding='utf-8'))
    return {'seed': settings['seed'], 'training': settings['training']}, settings, ROOT / settings['output']


def fingerprint():
    config, settings, _ = configuration(); warm = ROOT / settings['warm_start']; snapshot = ROOT / settings['snapshot']
    v80_summary = ROOT / 'artifacts/draft_ml/standard8-v80-universal/summary.json'
    digest = hashlib.sha256(json.dumps({'config': config, 'settings': settings}, sort_keys=True).encode())
    dependencies = (Path(__file__), CONFIG, ROOT / 'scripts/run_v74_resilient.py',
        ROOT / 'web/backend/services/draft_ml/v8_state.py', ROOT / 'web/backend/services/draft_ml/v8_network.py',
        ROOT / 'web/backend/services/draft_ml/v8_train.py', ROOT / 'web/backend/services/draft_evaluation.py',
        ROOT / 'web/backend/services/draft_ml/simulation.py', ROOT / 'core/z_score.py', ROOT / 'core/projection.py')
    for path in dependencies:
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    for path in (warm, snapshot, v80_summary): digest.update(sha(path).encode())
    return digest.hexdigest()


def initialize(checkpoint=None):
    global CTX, PLAYER_CACHE
    config, settings, _ = configuration()
    import torch
    torch.set_num_threads(1)
    snapshot = json.loads((ROOT / settings['snapshot']).read_text(encoding='utf-8'))
    policies = {'v80': UniversalPolicy(ROOT / settings['warm_start'])}
    if checkpoint: policies['v81'] = UniversalPolicy(checkpoint)
    CTX = config, settings, snapshot, policies
    PLAYER_CACHE = {}


def case_players(case):
    key = case['id']
    if key not in PLAYER_CACHE:
        PLAYER_CACHE[key] = prepare_players(CTX[2]['players'], case['categories'], case.get('reverse', ()))
    return PLAYER_CACHE[key]


def punt_profile(case, split, index):
    team_count = case['team_count']; cycle = index // team_count
    if split in ('validation_eval', 'holdout') and case['id'] in ('s8-t10-r13', 'holdout-s8-reference'):
        count = 0
    else:
        sequences = {'train': (0, 0, 0, 0, 1, 1, 2, 3), 'validation': (0, 2),
                     'validation_eval': (0, 1, 2, 3), 'holdout': (0, 1, 2, 3)}
        count = sequences[split][cycle % len(sequences[split])]
    rng = random.Random(f'v81:punt:{CTX[1]["seed"]}:{split}:{case["id"]}:{cycle}')
    punts = tuple(sorted(rng.sample(list(case['categories']), min(count, len(case['categories']) - 2))))
    return punts, {category: (0.0 if category in punts else 1.0) for category in case['categories']}


def random_weights(categories, seed, specialist=False, punt=False):
    rng = random.Random(seed)
    if specialist:
        focus = set(rng.sample(list(categories), min(3, len(categories))))
        return {category: (1.8 if category in focus else .25) for category in categories}
    weights = {category: rng.uniform(.4, 1.6) for category in categories}
    if punt:
        for category in rng.sample(list(categories), rng.choice((1, 2, min(3, len(categories) - 2)))): weights[category] = 0.0
    return weights


def opponent_assignments(case, seed):
    rng = random.Random(seed); result = {}
    for slot in range(1, case['team_count'] + 1):
        style = rng.choice(OPPONENT_STYLES)
        descriptor = {'style': style, 'weights': {category: 1.0 for category in case['categories']}}
        if style == 'weighted': descriptor['weights'] = random_weights(case['categories'], f'{seed}:{slot}')
        elif style == 'punt': descriptor['weights'] = random_weights(case['categories'], f'{seed}:{slot}', punt=True)
        elif style == 'specialist': descriptor['weights'] = random_weights(case['categories'], f'{seed}:{slot}', specialist=True)
        elif style == 'topk': descriptor['k'] = rng.choice((2, 3, 5, 7))
        result[slot] = descriptor
    return result


def heuristic_scores(state, weights, use_need=True):
    roster = state.context().roster
    totals = {category: sum(player.get('z_scores', {}).get(category, 0.0) for player in roster) for category in state.categories}
    needs = {category: 1.0 / (1.0 + math.exp(max(-20.0, min(20.0, totals[category] / 3.0)))) if use_need else 1.0
             for category in state.categories}
    open_positions = [position for position in POSITIONS if any(slot == position for slot in state.slots)]
    result = {}
    for index in state.legal():
        player = state.players[index]
        category_score = sum(weights[category] * needs[category] * player.get('z_scores', {}).get(category, 0.0)
                             for category in state.categories)
        flexibility = sum(compatible(player, position) for position in open_positions) / max(1, len(open_positions))
        result[index] = category_score + .15 * flexibility
    return result


def heuristic_action(state, weights, seed, descriptor=None):
    descriptor = descriptor or {'style': 'need', 'weights': weights}
    scores = heuristic_scores(state, descriptor.get('weights', weights), use_need=descriptor['style'] in ('need', 'topk'))
    ranked = sorted(scores, key=lambda index: (-scores[index], index))
    if descriptor['style'] == 'topk':
        return random.Random(f'{seed}:{state.pick}:{state.slot}').choice(ranked[:min(descriptor['k'], len(ranked))])
    return ranked[0]


def network_order(state, policy):
    legal = state.legal(); logits, _ = policy.predict(state, legal)
    return sorted(legal, key=lambda index: (-float(logits[index]), index)), logits


def policy_target(state, case, weights, settings, baseline):
    legal = state.legal(); scores = heuristic_scores(state, weights)
    target = np.zeros(len(state.players), dtype=np.float32)
    target[legal] = softmax([scores[index] for index in legal], settings['policy_temperature'])
    if tuple(case['categories']) == ('FG%', 'FT%', '3PM', 'REB', 'AST', 'STL', 'BLK', 'PTS') and all(value == 1.0 for value in weights.values()):
        _, logits = network_order(state, baseline); retained = np.zeros_like(target)
        retained[legal] = softmax(logits[legal], .5); blend = settings['standard8_baseline_blend']
        target = blend * retained + (1.0 - blend) * target
    return target


def objective(target, category_count, weights, categories):
    active = np.asarray([weights[category] for category in categories], dtype=np.float64)
    score = float(np.dot(target[:category_count], active) / max(1.0, active.sum()) * category_count)
    return score + .10 * float(target[category_count + 1]) + .05 * float(target[category_count + 2])


def finish(state, hero, opponents, seed, hero_weights):
    config, settings, _, _ = CTX
    while not state.complete:
        if state.slot == hero: action = heuristic_action(state, hero_weights, seed + ':hero')
        else: action = heuristic_action(state, opponents[state.slot]['weights'], seed, opponents[state.slot])
        state.apply(action)
    return state.targets(hero, seed, .12, .08)


def candidates(state, baseline, weights, count):
    network, _ = network_order(state, baseline); scores = heuristic_scores(state, weights)
    heuristic = sorted(scores, key=lambda index: (-scores[index], index))
    pools = [network[:4], heuristic[:4]]
    weakest = sorted(state.categories, key=lambda category: sum(p.get('z_scores', {}).get(category, 0.0) for p in state.context().roster))[:3]
    legal = state.legal()
    for category in weakest:
        pools.append([max(legal, key=lambda index: (weights[category] * state.players[index].get('z_scores', {}).get(category, 0.0), -index))])
    return list(dict.fromkeys(index for pool in pools for index in pool))[:count]


def searched_target(state, hero, case, weights, settings, baseline_target, key):
    ids = candidates(state, CTX[3]['v80'], weights, settings['search_candidates'])
    baseline_action = int(np.argmax(baseline_target)); selected = {}
    for candidate in ids:
        selected[candidate] = []
        for rollout in range(settings['search_rollouts']):
            branch = state.clone(); branch.apply(candidate)
            opponents = opponent_assignments(case, f'{key}:select:{rollout}')
            selected[candidate].append(finish(branch, hero, opponents, f'{key}:select:{rollout}', weights))
    values = {candidate: objective(np.mean(rows, axis=0), len(case['categories']), weights, case['categories'])
              for candidate, rows in selected.items()}
    chosen = max(ids, key=lambda index: (values[index], -index))
    audits = {}
    for candidate in set((baseline_action, chosen)):
        samples = []
        for rollout in range(settings['audit_rollouts']):
            branch = state.clone(); branch.apply(candidate)
            opponents = opponent_assignments(case, f'{key}:audit:{rollout}')
            samples.append(finish(branch, hero, opponents, f'{key}:audit:{rollout}', weights))
        audits[candidate] = objective(np.mean(samples, axis=0), len(case['categories']), weights, case['categories'])
    gain = audits[chosen] - audits[baseline_action]; accepted = chosen != baseline_action and gain >= settings['audit_min_gain']
    if not accepted: return baseline_target, baseline_action, {'accepted': False, 'gain': gain}
    search = np.zeros_like(baseline_target); search[ids] = softmax([values[index] for index in ids], settings['search_temperature'])
    blend = settings['search_policy_blend']
    return blend * baseline_target + (1.0 - blend) * search, chosen, {'accepted': True, 'gain': gain}


def search_rounds(rounds, count):
    return {min(rounds - 1, max(0, round((index + 1) * rounds / (count + 1)) - 1)) for index in range(count)}


def scenario(split, case, index):
    return f'v81:{CTX[1]["seed"]}:{split}:{case["id"]}:{index}'


def generate_episode(job):
    split, case, index, path, provenance = job
    config, settings, _, policies = CTX; key = scenario(split, case, index); players = case_players(case)
    hero = index % case['team_count'] + 1; punts, weights = punt_profile(case, split, index)
    state = UniversalState(players, case['slots'], case['team_count'], categories=case['categories'],
                           reverse_categories=case.get('reverse', ()), category_weights=weights)
    opponents = opponent_assignments(case, key); rounds_to_search = search_rounds(len(case['slots']), settings['search_states_per_episode'])
    records = []; policies_target = []; audits = []
    while not state.complete:
        if state.slot != hero:
            state.apply(heuristic_action(state, opponents[state.slot]['weights'], key, opponents[state.slot])); continue
        encoded = state.encode(); target = policy_target(state, case, weights, settings, policies['v80'])
        action = int(np.argmax(target)); own_round = len(state.rosters[hero])
        if own_round in rounds_to_search:
            target, action, audit = searched_target(state, hero, case, weights, settings, target, f'{key}:pick:{state.pick}')
            audits.append(audit)
        elif split == 'train' and random.Random(f'{key}:explore:{state.pick}').random() < .08:
            ranked = sorted(state.legal(), key=lambda index: (-target[index], index))[:4]
            action = int(random.Random(f'{key}:choice:{state.pick}').choice(ranked))
        records.append(encoded); policies_target.append(target); state.apply(action)
    terminal = np.mean([state.targets(hero, f'{key}:terminal:{draw}', .12, .08) for draw in range(settings['terminal_draws'])], axis=0)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as handle:
        np.savez_compressed(handle,
            raw=np.stack([row[0] for row in records]), category_values=np.stack([row[1] for row in records]),
            category_ids=records[0][2], category_meta=records[0][3], category_mask=records[0][4],
            roles=np.stack([row[5] for row in records]), global_state=np.stack([row[6] for row in records]),
            legal=np.stack([row[7] for row in records]), loss_mask=np.stack([row[7] for row in records]),
            policy=np.stack(policies_target), value_categories=np.repeat(terminal[None, :-3], len(records), axis=0),
            value_events=np.repeat(terminal[None, -3:], len(records), axis=0), scenario=np.asarray(key),
            provenance=np.asarray(provenance), format_id=np.asarray(case['id']), punts=np.asarray(json.dumps(punts)),
            audits=np.asarray(json.dumps(audits)))
    for attempt in range(21):
        try: os.replace(temporary, path); break
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.1)
    return {'accepted': sum(row['accepted'] for row in audits), 'searched': len(audits), 'format_id': case['id']}


def evaluation_episode(job):
    split, case, index = job
    _, settings, _, policies = CTX; key = f'v81:{settings["seed"]}:{split}:{case["id"]}:{index}'
    players = case_players(case); hero = index % case['team_count'] + 1; punts, weights = punt_profile(case, split, index)
    opponents = opponent_assignments(case, key); results = {}
    for mode in ('heuristic', 'v80', 'v81'):
        state = UniversalState(players, case['slots'], case['team_count'], categories=case['categories'],
                               reverse_categories=case.get('reverse', ()), category_weights=weights)
        while not state.complete:
            if state.slot != hero: action = heuristic_action(state, opponents[state.slot]['weights'], key, opponents[state.slot])
            elif mode == 'heuristic': action = heuristic_action(state, weights, key + ':hero')
            else: action = network_order(state, policies[mode])[0][0]
            state.apply(action)
        results[mode] = np.mean([state.targets(hero, f'{key}:terminal:{draw}', .12, .08)
                                 for draw in range(settings['terminal_draws'])], axis=0).tolist()
    return {'split': split, 'format_id': case['id'], 'episode': index, 'scenario': key, 'categories': case['categories'],
            'team_count': case['team_count'], 'punts': punts, 'results': results}


def metric(rows, left, right, z=1.96):
    values = {'normalized_categories': [], 'category_wins': [], 'rank_gain': [], 'top4': [], 'top1': []}
    for row in rows:
        count = len(row['categories']); teams = row['team_count']; a = row['results'][left]; b = row['results'][right]
        delta = sum(a[:count]) - sum(b[:count]); values['category_wins'].append(delta)
        values['normalized_categories'].append(delta / count); values['rank_gain'].append((b[count] - a[count]) * (teams - 1))
        values['top4'].append(a[count + 1] - b[count + 1]); values['top1'].append(a[count + 2] - b[count + 2])
    result = {}
    for name, raw in values.items():
        array = np.asarray(raw); mean = float(array.mean()); margin = float(z * array.std(ddof=1) / np.sqrt(len(array))) if len(array) > 1 else 0.0
        result[name] = {'delta': mean, 'interval': [mean - margin, mean + margin], 'n_drafts': len(array)}
    return result


def evaluation_report(rows, split):
    reference_id = 's8-t10-r13' if split == 'validation_eval' else 'holdout-s8-reference'
    reference = [row for row in rows if row['format_id'] == reference_id and not row['punts']]
    universal = [row for row in rows if row['format_id'] != reference_id]
    return {'primary': {'standard8_v81_vs_v80': metric(reference, 'v81', 'v80', 2.2414027276),
                        'universal_v81_vs_heuristic': metric(universal, 'v81', 'heuristic', 2.2414027276)},
        'pooled': {'v81_vs_v80': metric(rows, 'v81', 'v80'), 'v81_vs_heuristic': metric(rows, 'v81', 'heuristic')},
        'by_format': {format_id: {'v81_vs_v80': metric([row for row in rows if row['format_id'] == format_id], 'v81', 'v80'),
                                 'v81_vs_heuristic': metric([row for row in rows if row['format_id'] == format_id], 'v81', 'heuristic')}
                      for format_id in sorted({row['format_id'] for row in rows})},
        'by_punt_count': {str(count): {'v81_vs_v80': metric([row for row in rows if len(row['punts']) == count], 'v81', 'v80'),
                                      'v81_vs_heuristic': metric([row for row in rows if len(row['punts']) == count], 'v81', 'heuristic')}
                          for count in sorted({len(row['punts']) for row in rows})},
        'n_drafts': len(rows), 'reference_drafts': len(reference),
        'limitations': ['One historical player snapshot supplies every league format; this is not season generalization.',
                        'Synthetic opponent policies are broader than V7 but do not cover all human behaviour.',
                        'Two primary normalized-category contrasts use 97.5% Bonferroni intervals; other metrics are exploratory.',
                        'Punt profiles are explicit inputs. Automatic punt discovery is deferred to V8.2.']}


def parallel_jobs(settings, jobs, worker, consume, out, stage, checkpoint=None, existing=0, total=None):
    started = time.monotonic(); completed = 0; total = total if total is not None else existing + len(jobs)
    with ProcessPoolExecutor(max_workers=settings['workers'], initializer=initialize, initargs=(checkpoint,)) as pool:
        pending = {pool.submit(worker, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready: consume(future.result()); completed += 1
            elapsed = time.monotonic() - started
            save(out / 'stage-progress.json', {'stage': stage, 'completed': existing + completed, 'total': total,
                'eta_seconds': elapsed / completed * (len(jobs) - completed) if completed else None})


def phase(stage, expected):
    if fingerprint() != expected: raise ValueError('V8.1 stage code/input mismatch')
    config, settings, out = configuration()
    if stage == 'generate':
        jobs = []; expected_total = 0
        for split, cycles_key in (('train', 'train_cycles_per_seat'), ('validation', 'validation_data_cycles_per_seat')):
            for case in settings['formats']:
                count = case['team_count'] * settings[cycles_key]; expected_total += count
                for index in range(count):
                    path = out / 'data' / split / f"{case['id']}-{index:05d}.npz"
                    if path.exists():
                        with np.load(path, allow_pickle=False) as data:
                            if str(data['provenance']) != expected or str(data['scenario']) != f'v81:{settings["seed"]}:{split}:{case["id"]}:{index}':
                                raise ValueError(f'Incompatible data shard: {path}')
                    else: jobs.append((split, case, index, str(path), expected))
        stats = {'accepted': 0, 'searched': 0, 'formats': {}}
        def consume(row):
            stats['accepted'] += row['accepted']; stats['searched'] += row['searched']; stats['formats'][row['format_id']] = stats['formats'].get(row['format_id'], 0) + 1
        parallel_jobs(settings, jobs, generate_episode, consume, out, stage, existing=expected_total-len(jobs), total=expected_total)
        # Recompute totals over all shards so resume reports are complete.
        stats = {'accepted': 0, 'searched': 0, 'training_accepted': 0, 'formats': {}}
        for path in (out / 'data').glob('*/*.npz'):
            with np.load(path, allow_pickle=False) as data:
                audits = json.loads(str(data['audits'])); format_id = str(data['format_id'])
                stats['accepted'] += sum(row['accepted'] for row in audits); stats['searched'] += len(audits)
                stats['formats'][format_id] = stats['formats'].get(format_id, 0) + 1
                if path.parent.name == 'train': stats['training_accepted'] += sum(row['accepted'] for row in audits)
        save(out / 'data/complete.json', {'provenance': expected, **stats, 'shards': expected_total})
    elif stage == 'train':
        from web.backend.services.draft_ml.v8_train import fit
        fit(config, out / 'data', out / 'training', expected, ROOT / settings['warm_start'])
    else:
        split = stage; cases = settings['formats'] if split == 'validation_eval' else settings['holdout_formats']
        cycles = settings['validation_eval_cycles_per_seat'] if split == 'validation_eval' else settings['holdout_eval_cycles_per_seat']
        rows = []; jobs = []; total = sum(case['team_count'] * cycles for case in cases); checkpoint = out / 'training/best.pt'
        for case in cases:
            for index in range(case['team_count'] * cycles):
                path = out / split / f"{case['id']}-{index:05d}.json"
                if path.exists():
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if row['provenance'] != expected or row['checkpoint_sha256'] != sha(checkpoint): raise ValueError(f'Incompatible evaluation row: {path}')
                    rows.append(row)
                else: jobs.append((split, case, index))
        def consume(row):
            row.update(provenance=expected, checkpoint_sha256=sha(checkpoint)); rows.append(row)
            save(out / split / f"{row['format_id']}-{row['episode']:05d}.json", row)
        parallel_jobs(settings, jobs, evaluation_episode, consume, out, stage, str(checkpoint), len(rows), total)
        rows.sort(key=lambda row: (row['format_id'], row['episode']))
        save(out / split / 'summary.json', {**evaluation_report(rows, split), 'provenance': expected, 'checkpoint_sha256': sha(checkpoint)})


def validate_case(case, player_count):
    categories = normalize_categories(case['categories']); reverse = set(normalize_categories(case.get('reverse', ())) if case.get('reverse') else ())
    if reverse - set(categories): raise ValueError(f'Reverse category not active: {case["id"]}')
    if not 8 <= case['team_count'] <= 14 or not 9 <= len(case['slots']) <= 16: raise ValueError(f'Unsupported dimensions: {case["id"]}')
    if case['team_count'] * len(case['slots']) > player_count: raise ValueError(f'Player pool too small: {case["id"]}')


def plan():
    config, settings, out = configuration(); snapshot = json.loads((ROOT / settings['snapshot']).read_text(encoding='utf-8'))
    v80 = json.loads((ROOT / 'artifacts/draft_ml/standard8-v80-universal/summary.json').read_text())
    if v80['decision'] != 'V8_0_PARITY_PASSED_STOP_BEFORE_V8_1': raise ValueError('V8.0 parity did not pass')
    if sha(ROOT / settings['warm_start']) != v80['evaluation']['checkpoint_sha256']: raise ValueError('V8.0 checkpoint mismatch')
    ids = [case['id'] for case in (*settings['formats'], *settings['holdout_formats'])]
    if len(ids) != len(set(ids)): raise ValueError('Duplicate format id')
    for case in (*settings['formats'], *settings['holdout_formats']): validate_case(case, len(snapshot['players']))
    training_signatures = {(tuple(case['categories']), case['team_count'], tuple(case['slots'])) for case in settings['formats']}
    holdout_signatures = {(tuple(case['categories']), case['team_count'], tuple(case['slots'])) for case in settings['holdout_formats'] if case['id'] != 'holdout-s8-reference'}
    if training_signatures & holdout_signatures: raise ValueError('Holdout league configuration leakage')
    import torch
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if settings['training']['device'] == 'auto' else settings['training']['device']
    if device == 'cuda':
        probe = torch.ones((16, 16), device='cuda'); assert float((probe @ probe).sum()) == 4096
    data_drafts = sum(case['team_count'] * (settings['train_cycles_per_seat'] + settings['validation_data_cycles_per_seat']) for case in settings['formats'])
    validation_drafts = sum(case['team_count'] * settings['validation_eval_cycles_per_seat'] for case in settings['formats'])
    holdout_drafts = sum(case['team_count'] * settings['holdout_eval_cycles_per_seat'] for case in settings['holdout_formats'])
    searched_decisions = data_drafts * settings['search_states_per_episode']
    return {'status': 'PREPARED_NOT_STARTED', 'device': device, 'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None,
        'formats': len(settings['formats']), 'holdout_formats': len(settings['holdout_formats']), 'data_drafts': data_drafts,
        'searched_decisions': searched_decisions,
        'selection_continuations': searched_decisions * settings['search_candidates'] * settings['search_rollouts'],
        'audit_continuations_max': searched_decisions * 2 * settings['audit_rollouts'],
        'evaluation_drafts': validation_drafts + holdout_drafts, 'output': str(out),
        # Calibrated on 2026-09-13: s8-t10-r13 generation 175.3 s/episode on one
        # worker and evaluation 7.1 s/episode. The range includes larger formats,
        # six-worker scaling loss, filesystem overhead, and early stopping variance.
        'hours': {'generation': [13, 18], 'training': [.5, 2], 'validation': [.15, .5],
                  'holdout': [.1, .4], 'total': [14, 21]},
        'benchmark': {'generation_seconds_per_s8_t10_r13_episode': 175.3,
                      'evaluation_seconds_per_s8_t10_r13_episode': 7.1, 'workers': settings['workers']},
        'gates': {'minimum_training_accepts': settings['minimum_training_accepts'], 'standard8_normalized_delta_min': -.02,
                  'universal_vs_heuristic_normalized_delta_min': -.05},
        'resume': 'episode, epoch and evaluation scenario', 'auto_promote': False,
        'stopping': 'Stop on failed data/validation gate; always stop after frozen holdout for user review.'}


def run():
    prepared = plan(); digest = fingerprint(); _, settings, out = configuration(); out.mkdir(parents=True, exist_ok=True)
    with lock(out / 'run.lock'):
        journal_path = out / 'run-state.json'; journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'provenance': digest, 'completed': [], 'checksums': {}}
        if journal['provenance'] != digest: raise ValueError('Incompatible V8.1 resume')
        save(out / 'plan.json', prepared)
        def status(phase_name, error=None): save(out / 'status.json', {'pid': os.getpid(), 'phase': phase_name,
            'completed': len(journal['completed']), 'total': 4, 'provenance': digest, 'error': error,
            'updated_at': time.time(), 'training': True})
        def checks(stage):
            if stage == 'generate': files = [*sorted((out / 'data').glob('*/*.npz')), out / 'data/complete.json']
            elif stage == 'train': files = [out / 'training/best.pt', out / 'training/complete.json']
            else: files = [out / stage / 'summary.json']
            return {str(path.relative_to(out)): sha(path) for path in files}
        try:
            for stage in ('generate', 'train', 'validation_eval', 'holdout'):
                if stage == 'train':
                    data = json.loads((out / 'data/complete.json').read_text())
                    if data['training_accepted'] < settings['minimum_training_accepts']:
                        save(out / 'gate.json', {'passed': False, 'reason': 'Too few accepted training improvements',
                            'training_accepted': data['training_accepted']}); status('STOP_FOR_REVIEW'); return
                if stage == 'holdout':
                    validation = json.loads((out / 'validation_eval/summary.json').read_text())
                    standard8 = validation['primary']['standard8_v81_vs_v80']['normalized_categories']['delta']
                    universal = validation['primary']['universal_v81_vs_heuristic']['normalized_categories']['delta']
                    if standard8 < -.02 or universal < -.05:
                        save(out / 'gate.json', {'passed': False, 'reason': 'Validation regression; holdout unopened',
                            'standard8_delta': standard8, 'universal_delta': universal}); status('STOP_FOR_REVIEW'); return
                    frozen = {'checkpoint_sha256': sha(out / 'training/best.pt'), 'provenance': digest}
                    if (out / 'frozen.json').exists() and json.loads((out / 'frozen.json').read_text()) != frozen: raise ValueError('Frozen V8.1 checkpoint changed')
                    save(out / 'frozen.json', frozen)
                if stage in journal['completed']:
                    if checks(stage) != journal['checksums'][stage]: raise ValueError(f'Completed V8.1 artifact changed: {stage}')
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
                if child.returncode: raise RuntimeError(f'{stage} failed; progress retained')
                journal['completed'].append(stage); journal['checksums'][stage] = checks(stage); save(journal_path, journal)
            holdout = json.loads((out / 'holdout/summary.json').read_text())
            save(out / 'summary.json', {'provenance': digest, 'holdout': holdout, 'decision': 'STOP_FOR_USER_REVIEW_NO_PROMOTION'})
            status('COMPLETE')
        except BaseException:
            status('FAILED', traceback.format_exc()); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stage', choices=('generate', 'train', 'validation_eval', 'holdout')); parser.add_argument('--provenance')
    args = parser.parse_args()
    if args.stage: phase(args.stage, args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(), indent=2))
