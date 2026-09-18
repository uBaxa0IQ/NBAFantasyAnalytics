"""V8.1.1 frozen-base residual adapters, validation selection and sealed holdout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from scripts import draft_v81_multiformat as v81
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha
from web.backend.services.draft_ml.v8_state import UniversalState
from web.backend.services.draft_ml.v811_train import fit_residual, scaled_checkpoint

CONFIG = ROOT / 'configs/draft_ml_v811.json'


def configuration():
    settings = json.loads(CONFIG.read_text(encoding='utf-8'))
    return settings, ROOT / settings['output'], ROOT / settings['v81_output']


def fingerprint():
    settings, _, source = configuration()
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    dependencies = (Path(__file__), CONFIG, ROOT / 'scripts/draft_v81_multiformat.py',
        ROOT / 'web/backend/services/draft_ml/v8_state.py', ROOT / 'web/backend/services/draft_ml/v8_network.py',
        ROOT / 'web/backend/services/draft_ml/v8_train.py', ROOT / 'web/backend/services/draft_ml/v811_train.py')
    for path in dependencies:
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    for path in (ROOT / settings['warm_start'], source / 'data/complete.json', source / 'run-state.json',
                 source / 'validation_eval/summary.json'):
        digest.update(sha(path).encode())
    return digest.hexdigest()


def validate_source(settings, source):
    status = json.loads((source / 'status.json').read_text())
    journal = json.loads((source / 'run-state.json').read_text())
    data = json.loads((source / 'data/complete.json').read_text())
    gate = json.loads((source / 'gate.json').read_text())
    if status['phase'] != 'STOP_FOR_REVIEW' or journal['completed'] != ['generate', 'train', 'validation_eval']:
        raise ValueError('V8.1 source is not the expected completed validation run')
    if gate.get('passed') is not False or data['shards'] != 1320 or data['training_accepted'] < 100:
        raise ValueError('V8.1 source data is incomplete or invalid')
    if sha(ROOT / settings['warm_start']) != json.loads(
            (ROOT / 'artifacts/draft_ml/standard8-v80-universal/summary.json').read_text())['evaluation']['checkpoint_sha256']:
        raise ValueError('V8.0 warm-start checkpoint mismatch')
    return data


def candidate_name(seed, scale):
    return f'seed-{seed}-scale-{scale:.3f}'.replace('.', 'p')


def candidate_episode(job):
    split, case, index = job
    _, settings, _, policies = v81.CTX
    key = f'v81:{settings["seed"]}:{split}:{case["id"]}:{index}'
    players = v81.case_players(case); hero = index % case['team_count'] + 1
    punts, weights = v81.punt_profile(case, split, index); opponents = v81.opponent_assignments(case, key)
    state = UniversalState(players, case['slots'], case['team_count'], categories=case['categories'],
                           reverse_categories=case.get('reverse', ()), category_weights=weights)
    while not state.complete:
        if state.slot != hero:
            action = v81.heuristic_action(state, opponents[state.slot]['weights'], key, opponents[state.slot])
        else:
            action = v81.network_order(state, policies['v81'])[0][0]
        state.apply(action)
    result = np.mean([state.targets(hero, f'{key}:terminal:{draw}', .12, .08)
                      for draw in range(settings['terminal_draws'])], axis=0).tolist()
    return {'split': split, 'format_id': case['id'], 'episode': index, 'scenario': key,
            'categories': case['categories'], 'team_count': case['team_count'], 'punts': punts, 'result': result}


def full_holdout_episode(job):
    row = v81.evaluation_episode(job)
    row['results']['v811'] = row['results'].pop('v81')
    return row


def report(rows, split):
    reference_id = 's8-t10-r13' if split == 'validation_eval' else 'holdout-s8-reference'
    reference = [row for row in rows if row['format_id'] == reference_id and not row['punts']]
    universal = [row for row in rows if row['format_id'] != reference_id]
    return {'primary': {
        'standard8_v811_vs_v80': v81.metric(reference, 'v811', 'v80', 2.2414027276),
        'universal_v811_vs_v80': v81.metric(universal, 'v811', 'v80', 2.2414027276),
        'universal_v811_vs_heuristic': v81.metric(universal, 'v811', 'heuristic', 2.2414027276)},
        'pooled': {'v811_vs_v80': v81.metric(rows, 'v811', 'v80'),
                   'v811_vs_heuristic': v81.metric(rows, 'v811', 'heuristic')},
        'by_format': {format_id: {'v811_vs_v80': v81.metric([r for r in rows if r['format_id'] == format_id], 'v811', 'v80'),
                                 'v811_vs_heuristic': v81.metric([r for r in rows if r['format_id'] == format_id], 'v811', 'heuristic')}
                      for format_id in sorted({row['format_id'] for row in rows})},
        'by_punt_count': {str(count): {'v811_vs_v80': v81.metric([r for r in rows if len(r['punts']) == count], 'v811', 'v80'),
                                      'v811_vs_heuristic': v81.metric([r for r in rows if len(r['punts']) == count], 'v811', 'heuristic')}
                          for count in sorted({len(row['punts']) for row in rows})},
        'n_drafts': len(rows), 'reference_drafts': len(reference)}


def evaluate_candidate(settings, source, out, checkpoint, seed, scale, expected):
    name = candidate_name(seed, scale); directory = out / 'validation' / name
    cases = v81.configuration()[1]['formats']; cycles = v81.configuration()[1]['validation_eval_cycles_per_seat']
    rows = []; jobs = []; total = sum(case['team_count'] * cycles for case in cases)
    checkpoint_hash = sha(checkpoint)
    for case in cases:
        for index in range(case['team_count'] * cycles):
            path = directory / f"{case['id']}-{index:05d}.json"
            if path.exists():
                row = json.loads(path.read_text())
                if row['provenance'] != expected or row['checkpoint_sha256'] != checkpoint_hash:
                    raise ValueError(f'Incompatible V8.1.1 validation row: {path}')
                rows.append(row)
            else:
                jobs.append(('validation_eval', case, index))
    def consume(candidate):
        base_path = source / 'validation_eval' / f"{candidate['format_id']}-{candidate['episode']:05d}.json"
        base = json.loads(base_path.read_text())
        if base['scenario'] != candidate['scenario'] or list(base['punts']) != list(candidate['punts']):
            raise ValueError(f'Paired baseline mismatch: {base_path}')
        candidate['results'] = {'heuristic': base['results']['heuristic'], 'v80': base['results']['v80'],
                                'v811': candidate.pop('result')}
        candidate.update(provenance=expected, checkpoint_sha256=checkpoint_hash, seed=seed, adapter_scale=scale)
        rows.append(candidate); save(directory / f"{candidate['format_id']}-{candidate['episode']:05d}.json", candidate)
    v81.parallel_jobs(settings, jobs, candidate_episode, consume, out, 'validation:' + name,
                      str(checkpoint), total - len(jobs), total)
    rows.sort(key=lambda row: (row['format_id'], row['episode']))
    result = report(rows, 'validation_eval')
    result.update({'candidate': name, 'seed': seed, 'adapter_scale': scale,
                   'checkpoint_sha256': checkpoint_hash, 'provenance': expected})
    save(directory / 'summary.json', result)
    return result


def qualifying_score(summary, gates):
    ref = summary['primary']['standard8_v811_vs_v80']['normalized_categories']
    universal = summary['primary']['universal_v811_vs_v80']['normalized_categories']
    heuristic = summary['primary']['universal_v811_vs_heuristic']['normalized_categories']
    passed = (ref['delta'] >= gates['standard8_delta_min'] and ref['interval'][0] >= gates['standard8_interval_low_min']
              and universal['delta'] >= gates['universal_v80_delta_min']
              and universal['interval'][0] >= gates['universal_v80_interval_low_min']
              and heuristic['delta'] >= gates['universal_heuristic_delta_min'])
    return passed, universal['delta'] + .25 * ref['delta']


def phase(stage, expected):
    if fingerprint() != expected:
        raise ValueError('V8.1.1 code/input fingerprint changed')
    settings, out, source = configuration(); v81_settings = v81.configuration()[1]
    if stage == 'train':
        for seed in settings['training_seeds']:
            fit_residual(settings, source / 'data', out / 'training' / f'seed-{seed}', expected,
                         ROOT / settings['warm_start'], seed)
    elif stage == 'validation':
        summaries = []
        for seed in settings['training_seeds']:
            base = out / 'training' / f'seed-{seed}' / 'best.pt'
            for scale in settings['adapter_scales']:
                checkpoint = out / 'candidates' / (candidate_name(seed, scale) + '.pt')
                if not checkpoint.exists():
                    scaled_checkpoint(base, checkpoint, scale, expected)
                else:
                    payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
                    if payload['provenance'] != expected or float(payload['adapter_scale']) != float(scale):
                        raise ValueError(f'Incompatible candidate checkpoint: {checkpoint}')
                summaries.append(evaluate_candidate(settings, source, out, checkpoint, seed, scale, expected))
        eligible = []
        for summary in summaries:
            passed, score = qualifying_score(summary, settings['validation_gates'])
            if passed: eligible.append((score, summary))
        compact = [{'candidate': row['candidate'], 'seed': row['seed'], 'adapter_scale': row['adapter_scale'],
                    'standard8_delta': row['primary']['standard8_v811_vs_v80']['normalized_categories']['delta'],
                    'universal_v80_delta': row['primary']['universal_v811_vs_v80']['normalized_categories']['delta'],
                    'universal_heuristic_delta': row['primary']['universal_v811_vs_heuristic']['normalized_categories']['delta']}
                   for row in summaries]
        if not eligible:
            save(out / 'selection.json', {'passed': False, 'reason': 'No residual candidate passed validation gates',
                                          'candidates': compact, 'provenance': expected}); return
        _, chosen = max(eligible, key=lambda item: (item[0], -item[1]['adapter_scale']))
        raw = out / 'training' / f"seed-{chosen['seed']}" / 'best.pt'
        frozen = scaled_checkpoint(raw, out / 'frozen.pt', chosen['adapter_scale'], expected)
        save(out / 'selection.json', {'passed': True, 'chosen': chosen['candidate'], 'seed': chosen['seed'],
            'adapter_scale': chosen['adapter_scale'], 'checkpoint_sha256': sha(frozen), 'candidates': compact,
            'gates': settings['validation_gates'], 'provenance': expected})
    else:
        selection = json.loads((out / 'selection.json').read_text())
        if not selection['passed']: raise ValueError('Holdout cannot open before a passing validation selection')
        cases = v81_settings['holdout_formats']; cycles = v81_settings['holdout_eval_cycles_per_seat']
        rows = []; jobs = []; total = sum(case['team_count'] * cycles for case in cases); checkpoint = out / 'frozen.pt'
        for case in cases:
            for index in range(case['team_count'] * cycles):
                path = out / 'holdout' / f"{case['id']}-{index:05d}.json"
                if path.exists():
                    row = json.loads(path.read_text())
                    if row['provenance'] != expected or row['checkpoint_sha256'] != sha(checkpoint):
                        raise ValueError(f'Incompatible V8.1.1 holdout row: {path}')
                    rows.append(row)
                else: jobs.append(('holdout', case, index))
        def consume(row):
            row.update(provenance=expected, checkpoint_sha256=sha(checkpoint))
            rows.append(row); save(out / 'holdout' / f"{row['format_id']}-{row['episode']:05d}.json", row)
        # Holdout has never been opened, so all three paired policies are run in workers.
        v81.parallel_jobs(settings, jobs, full_holdout_episode, consume, out, 'holdout',
                          str(checkpoint), total-len(jobs), total)
        rows.sort(key=lambda row: (row['format_id'], row['episode']))
        save(out / 'holdout/summary.json', {**report(rows, 'holdout'), 'selection': selection,
                                            'provenance': expected, 'checkpoint_sha256': sha(checkpoint)})


def plan():
    settings, out, source = configuration(); data = validate_source(settings, source)
    v81_settings = v81.configuration()[1]
    validation_drafts = sum(case['team_count'] * v81_settings['validation_eval_cycles_per_seat']
                            for case in v81_settings['formats'])
    holdout_drafts = sum(case['team_count'] * v81_settings['holdout_eval_cycles_per_seat']
                         for case in v81_settings['holdout_formats'])
    train_states = sum(case['team_count'] * v81_settings['train_cycles_per_seat'] * len(case['slots'])
                       for case in v81_settings['formats'])
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    return {'status': 'PREPARED_NOT_STARTED', 'source_shards_reused': data['shards'], 'new_generation_drafts': 0,
        'training_states': train_states, 'seeds': len(settings['training_seeds']),
        'scales_per_seed': len(settings['adapter_scales']),
        'validation_candidate_drafts': validation_drafts * len(settings['training_seeds']) * len(settings['adapter_scales']),
        'sealed_holdout_drafts': holdout_drafts, 'device': device,
        'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None, 'output': str(out),
        'hours': {'adapter_training': [.5, 1.5], 'validation_selection': [1, 2.5],
                  'holdout': [.15, .5], 'total': [2, 4.5]},
        'resume': 'seed, epoch, candidate and evaluation scenario', 'auto_promote': False,
        'stopping': 'Stop if no candidate beats V8.0 under retention gates; otherwise open holdout and stop for review.'}


def run():
    prepared = plan(); expected = fingerprint(); settings, out, _ = configuration(); out.mkdir(parents=True, exist_ok=True)
    with lock(out / 'run.lock'):
        journal_path = out / 'run-state.json'
        journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'provenance': expected, 'completed': []}
        if journal['provenance'] != expected: raise ValueError('Incompatible V8.1.1 resume')
        save(out / 'plan.json', prepared)
        def status(phase_name, error=None): save(out / 'status.json', {'pid': os.getpid(), 'phase': phase_name,
            'completed': len(journal['completed']), 'total': 3, 'provenance': expected, 'error': error,
            'updated_at': time.time(), 'training': True})
        child = None
        try:
            for stage in ('train', 'validation', 'holdout'):
                if stage == 'holdout':
                    selection = json.loads((out / 'selection.json').read_text())
                    if not selection['passed']:
                        status('STOP_FOR_REVIEW'); return
                if stage in journal['completed']: continue
                status('RUNNING:' + stage)
                with (out / f'{stage}.log').open('a', encoding='utf-8') as handle:
                    child = subprocess.Popen([sys.executable, '-u', str(Path(__file__)), '--stage', stage,
                                              '--provenance', expected], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
                    while child.poll() is None:
                        try: child.wait(timeout=15)
                        except subprocess.TimeoutExpired: status('RUNNING:' + stage)
                if child.returncode: raise RuntimeError(f'{stage} failed; progress retained')
                journal['completed'].append(stage); save(journal_path, journal)
            status('COMPLETE')
        except BaseException as exc:
            if child is not None and child.poll() is None:
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True)
            status('FAILED', ''.join(traceback.format_exception_only(type(exc), exc)).strip()); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stage', choices=('train', 'validation', 'holdout')); parser.add_argument('--provenance')
    args = parser.parse_args()
    if args.stage:
        phase(args.stage, args.provenance)
    elif args.execute:
        run()
    else:
        print(json.dumps(plan(), indent=2))
