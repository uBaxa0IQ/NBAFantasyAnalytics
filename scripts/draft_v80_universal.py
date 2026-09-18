"""Migrate V7.6 exactly into the V8 universal architecture and verify parity."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
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

from scripts import draft_v73_diagnostic as base
from scripts import draft_v77_stability as v77
from scripts import resume_v76_verified as verified
from scripts.draft_ml_v7_run import lock, preflight
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import State as V7State, sha
from web.backend.services.draft_ml.v8_network import UniversalPolicy, migrate_v7_checkpoint
from web.backend.services.draft_ml.v8_state import UniversalState

CONFIG = ROOT / 'configs/draft_ml_v80.json'
OUTPUT = ROOT / 'artifacts/draft_ml/standard8-v80-universal'
CONDITIONS = ('strong', 'mixed', 'unseen_rules', 'projection_shift')
POLICIES = None


def configuration():
    settings = json.loads(CONFIG.read_text(encoding='utf-8'))
    config = json.loads((ROOT / 'configs/draft_ml_v7.json').read_text(encoding='utf-8'))
    config.update(seed=settings['seed'], workers=settings['workers'])
    return config, settings, ROOT / settings['output']


def fingerprint():
    old_output = ROOT / 'artifacts/draft_ml/standard8-v76-distillation'
    # V7.6's resume wrapper intentionally rejects any newly added service file.
    # V8 is a new experiment, so verify the frozen artifacts without installing
    # that historical source-tree import guard.
    old_journal = verified.check(old_output)
    config, settings, _ = configuration()
    source = ROOT / settings['source_checkpoint']
    digest = hashlib.sha256(json.dumps({'config': config, 'settings': settings, 'v76': old_journal}, sort_keys=True).encode())
    dependencies = (Path(__file__), CONFIG, ROOT / 'scripts/draft_v77_stability.py', ROOT / 'scripts/draft_v73_diagnostic.py',
        ROOT / 'scripts/resume_v76_verified.py', ROOT / 'scripts/run_v74_resilient.py',
        ROOT / 'web/backend/services/draft_ml/v8_state.py', ROOT / 'web/backend/services/draft_ml/v8_network.py',
        ROOT / 'web/backend/services/draft_ml/v7_state.py', ROOT / 'web/backend/services/draft_ml/v7_network.py',
        ROOT / 'web/backend/services/draft_ml/evolution.py', ROOT / 'web/backend/services/draft_evaluation.py',
        ROOT / 'core/z_score.py', ROOT / 'core/projection.py')
    for path in dependencies:
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    digest.update(sha(source).encode())
    return digest.hexdigest()


def initialize(checkpoint):
    global POLICIES
    config, settings, _ = configuration(); base.initialize(config, settings)
    from web.backend.services.draft_ml.v7_network import NeuralPolicy
    POLICIES = {'old': base.CTX[3].history[2], 'v76': NeuralPolicy(ROOT / settings['source_checkpoint']),
                'v80': UniversalPolicy(checkpoint)}


def states(players, payload, config):
    return (V7State(players, payload['roster_slots'], config['team_count'], config['rounds']),
            UniversalState(players, payload['roster_slots'], config['team_count'], config['rounds'], payload['categories']))


def numeric_parity(checkpoint):
    initialize(checkpoint)
    config, settings, payload, arena = base.CTX
    max_logit = max_value = 0.0; compared = action_disagreements = 0
    for index in range(settings['numeric_parity_drafts']):
        key = f'v80:{settings["seed"]}:numeric:{index}'; hero = index % config['team_count'] + 1
        assignments = base.assignments_for(arena, 'mixed' if index % 2 else 'strong', key)
        old_state, new_state = states(payload['players'], payload, config)
        while not old_state.complete:
            if old_state.legal() != new_state.legal() or old_state.slot != new_state.slot:
                raise ValueError('V8 state legality diverged from V7')
            if old_state.slot == hero:
                legal = old_state.legal()
                old_logits, old_values = POLICIES['v76'].predict(old_state, legal)
                new_logits, new_values = POLICIES['v80'].predict(new_state, legal)
                max_logit = max(max_logit, float(np.max(np.abs(old_logits[legal] - new_logits[legal]))))
                max_value = max(max_value, float(np.max(np.abs(old_values - new_values))))
                old_action = max(legal, key=lambda i: (float(old_logits[i]), -i))
                new_action = max(legal, key=lambda i: (float(new_logits[i]), -i))
                action_disagreements += int(old_action != new_action); compared += 1; action = old_action
            else:
                action = arena.opponent_action(old_state, assignments, key)
            old_state.apply(action); new_state.apply(action)
    passed = action_disagreements == 0 and max_logit <= settings['parity_logit_tolerance'] and max_value <= settings['parity_value_tolerance']
    return {'passed': passed, 'drafts': settings['numeric_parity_drafts'], 'states': compared,
            'action_disagreements': action_disagreements, 'max_legal_logit_error': max_logit, 'max_value_error': max_value,
            'tolerances': {'logit': settings['parity_logit_tolerance'], 'value': settings['parity_value_tolerance']}}


def episode(job):
    condition, index = job
    config, settings, payload, arena = base.CTX
    key = f'v80:{settings["seed"]}:evaluation:{condition}:{index}'; hero = index % config['team_count'] + 1
    players = v77.shifted_players(payload['players'], key + ':inputs') if condition == 'projection_shift' else payload['players']
    assignments = base.assignments_for(arena, 'mixed' if condition in ('mixed', 'projection_shift') else 'strong', key)
    # Run the old reference independently.
    old_state = V7State(players, payload['roster_slots'], config['team_count'], config['rounds']); old_actions = []
    while not old_state.complete:
        if old_state.slot == hero:
            legal = old_state.legal(); logits, _ = POLICIES['old'].predict(old_state, legal)
            action = max(legal, key=lambda i: (float(logits[i]), -i)); old_actions.append(action)
        elif condition == 'unseen_rules': action = v77.rule_action(old_state, arena, key)
        else: action = arena.opponent_action(old_state, assignments, key + ':actual')
        old_state.apply(action)

    # V7.6 and V8.0 advance in lockstep. Opponents are calculated once from the
    # V7-compatible state, so this tests our policy/state migration without
    # asking a V7 opponent network to consume V8 tensors.
    state7, state8 = states(players, payload, config); actions7 = []; actions8 = []
    while not state7.complete:
        if state7.legal() != state8.legal() or state7.slot != state8.slot:
            raise ValueError('Full-draft V8 state legality diverged from V7')
        if state7.slot == hero:
            legal = state7.legal(); logits7, _ = POLICIES['v76'].predict(state7, legal); logits8, _ = POLICIES['v80'].predict(state8, legal)
            action7 = max(legal, key=lambda i: (float(logits7[i]), -i)); action8 = max(legal, key=lambda i: (float(logits8[i]), -i))
            actions7.append(action7); actions8.append(action8); action = action7
        elif condition == 'unseen_rules': action = v77.rule_action(state7, arena, key)
        else: action = arena.opponent_action(state7, assignments, key + ':actual')
        state7.apply(action); state8.apply(action)

    def targets(state):
        return np.mean([state.targets(hero, f'{key}:terminal:{draw}', config['gp_stddev'], config['stat_stddev'])
                        for draw in range(settings['terminal_draws'])], axis=0).tolist()
    results = {'old': targets(old_state), 'v76': targets(state7), 'v80': targets(state8)}
    actions = {'old': old_actions, 'v76': actions7, 'v80': actions8}
    return {'condition': condition, 'episode': index, 'scenario': key, 'results': results, 'actions': actions,
            'v80_v76_action_equal': actions['v80'] == actions['v76']}


def comparison(rows, left, right):
    a = np.asarray([row['results'][left] for row in rows]); b = np.asarray([row['results'][right] for row in rows])
    values = {'categories': a[:, :8].sum(1) - b[:, :8].sum(1), 'rank_gain': 9 * (b[:, 8] - a[:, 8]),
              'top4': a[:, 9] - b[:, 9], 'top1': a[:, 10] - b[:, 10]}
    return {name: {'delta': float(value.mean()), 'max_absolute': float(np.max(np.abs(value))), 'n_drafts': len(value)}
            for name, value in values.items()}


def report(rows):
    parity = comparison(rows, 'v80', 'v76')
    return {'parity_v80_vs_v76': parity, 'v80_vs_old': comparison(rows, 'v80', 'old'),
        'by_condition': {condition: {'v80_vs_v76': comparison([row for row in rows if row['condition'] == condition], 'v80', 'v76'),
                                    'v80_vs_old': comparison([row for row in rows if row['condition'] == condition], 'v80', 'old')}
                         for condition in CONDITIONS},
        'action_disagreement_drafts': sum(not row['v80_v76_action_equal'] for row in rows), 'n_drafts': len(rows),
        'passed': all(metric['max_absolute'] <= 1e-9 for metric in parity.values()) and all(row['v80_v76_action_equal'] for row in rows),
        'limitations': ['V8.0 establishes exact standard8 migration and technical variable-shape support, not multi-format strength.',
                        'No V8 training occurs. V8.1 must train on multiple category/team/roster formats.',
                        'Same historical player snapshot and synthetic opponents; no production promotion.']}


def evaluate(checkpoint, provenance):
    config, settings, out = configuration(); rows, jobs = [], []
    for condition in CONDITIONS:
        for index in range(settings['evaluation_per_condition']):
            path = out / 'evaluation' / f'{condition}-{index:04d}.json'
            if path.exists():
                row = json.loads(path.read_text(encoding='utf-8'))
                if row['provenance'] != provenance or row['checkpoint_sha256'] != sha(checkpoint):
                    raise ValueError(f'Incompatible saved evaluation: {path}')
                rows.append(row)
            else:
                jobs.append((condition, index))
    started = time.monotonic(); completed = 0
    with ProcessPoolExecutor(max_workers=settings['workers'], initializer=initialize, initargs=(str(checkpoint),)) as pool:
        pending = {pool.submit(episode, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                row = future.result(); row.update(provenance=provenance, checkpoint_sha256=sha(checkpoint)); rows.append(row)
                save(out / 'evaluation' / f"{row['condition']}-{row['episode']:04d}.json", row); completed += 1
            elapsed = time.monotonic() - started
            save(out / 'stage-progress.json', {'stage': 'evaluate', 'completed': len(rows),
                'total': len(CONDITIONS) * settings['evaluation_per_condition'],
                'eta_seconds': elapsed / completed * (len(jobs) - completed) if completed else None})
    rows.sort(key=lambda row: (row['condition'], row['episode']))
    result = report(rows); result.update(provenance=provenance, checkpoint_sha256=sha(checkpoint))
    save(out / 'evaluation/summary.json', result)


def phase(stage, expected):
    if fingerprint() != expected: raise ValueError('Stage code/input mismatch')
    config, settings, out = configuration(); checkpoint = out / 'checkpoint/best.pt'
    if stage == 'migrate':
        migrate_v7_checkpoint(ROOT / settings['source_checkpoint'], checkpoint, expected)
    elif stage == 'numeric':
        result = numeric_parity(checkpoint); save(out / 'numeric-parity.json', result)
        if not result['passed']: raise RuntimeError('Numerical parity gate failed')
    else:
        evaluate(checkpoint, expected)
        if not json.loads((out / 'evaluation/summary.json').read_text())['passed']:
            raise RuntimeError('Full-draft parity gate failed')


def plan():
    config, settings, out = configuration(); audit = preflight(config, hardware=True)
    if out != OUTPUT: raise ValueError('Output config mismatch')
    if not (ROOT / settings['source_checkpoint']).exists(): raise ValueError('V7.6 source checkpoint is missing')
    if not 8 <= config['team_count'] <= 14: raise ValueError('Parity source must be within V8 supported range')
    return {'status': 'PREPARED_NOT_STARTED', 'purpose': 'Exact V7.6 -> league-conditioned V8.0 migration and standard8 parity gate',
        'audit': audit, 'settings': settings, 'conditions': list(CONDITIONS),
        'numeric_states': settings['numeric_parity_drafts'] * config['rounds'],
        'evaluation_drafts': len(CONDITIONS) * settings['evaluation_per_condition'],
        'supported_architecture': {'categories': list(__import__('web.backend.services.draft_ml.v8_state', fromlist=['CATEGORY_VOCAB']).CATEGORY_VOCAB),
                                   'team_count': [8, 14], 'variable_rounds_and_roster_slots': True, 'category_weights_and_punts': True},
        'hours': {'migration_and_numeric': [.05, .2], 'full_draft_parity': [.25, .8], 'total': [.3, 1.0]},
        'next_after_pass': 'Prepare V8.1 multi-format data generation and training; V8.0 itself never trains or promotes.'}


def run():
    prepared = plan(); digest = fingerprint(); _, _, out = configuration(); out.mkdir(parents=True, exist_ok=True)
    with lock(out / 'run.lock'):
        journal_path = out / 'run-state.json'
        journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'provenance': digest, 'completed': [], 'checksums': {}}
        if journal['provenance'] != digest: raise ValueError('Incompatible V8.0 resume')
        save(out / 'plan.json', prepared)
        def status(phase_name, error=None):
            save(out / 'status.json', {'pid': os.getpid(), 'phase': phase_name, 'completed': len(journal['completed']),
                'total': 3, 'provenance': digest, 'error': error, 'updated_at': time.time(), 'training': False})
        def checks(stage):
            files = {'migrate': [out / 'checkpoint/best.pt'], 'numeric': [out / 'numeric-parity.json'],
                     'evaluate': [out / 'evaluation/summary.json']}[stage]
            return {str(path.relative_to(out)): sha(path) for path in files}
        try:
            for stage in ('migrate', 'numeric', 'evaluate'):
                if stage in journal['completed']:
                    if journal['checksums'][stage] != checks(stage): raise ValueError(f'Completed V8.0 artifact changed: {stage}')
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
            save(out / 'summary.json', {'provenance': digest, 'numeric': json.loads((out / 'numeric-parity.json').read_text()),
                'evaluation': json.loads((out / 'evaluation/summary.json').read_text()),
                'decision': 'V8_0_PARITY_PASSED_STOP_BEFORE_V8_1' })
            status('COMPLETE')
        except BaseException:
            status('FAILED', traceback.format_exc()); raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--stage', choices=('migrate', 'numeric', 'evaluate'))
    parser.add_argument('--provenance')
    args = parser.parse_args()
    if args.stage: phase(args.stage, args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(), indent=2))
