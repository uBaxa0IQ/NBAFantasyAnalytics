"""V7 staged research runner. Dry plan by default; explicit --execute required."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web.backend.services.draft_ml.v7_data import atomic_json
from web.backend.services.draft_ml.v7_state import validate_snapshot, unique_teacher, sha

CONFIG = ROOT / 'configs/draft_ml_v7.json'


def paths(config):
    return tuple(ROOT / config[key] for key in ('snapshot', 'teacher', 'output'))


def preflight(config, hardware=False):
    snapshot, teacher, out = paths(config)
    payload = json.loads(snapshot.read_text(encoding='utf-8'))
    audit = validate_snapshot(payload, config['team_count'], config['rounds'])
    manifest = json.loads((teacher / 'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['artifact_sha256'].items():
        if sha(teacher / name) != digest:
            raise ValueError('Teacher checksum mismatch')
    genomes = json.loads((teacher / 'genomes.json').read_text(encoding='utf-8'))
    audit.update({'teacher_members': len(genomes), 'unique_teacher_members': len(unique_teacher(genomes)),
                  'projection_sources': sorted({p.get('stats_source', 'unknown') for p in payload['players']})})
    if config['team_count'] != 10 or config['rounds'] != 13:
        raise ValueError('First V7 run is frozen to 10 teams and 13 players')
    if not 1 <= config['workers'] <= 8 or config['search']['rollouts'] < 1 or config['search']['candidates'] < 2:
        raise ValueError('Invalid execution/search budget')
    if any(config['model'][key] < 1 for key in ('width', 'heads', 'layers')):
        raise ValueError('Model dimensions must be positive')
    if config['model']['width'] % config['model']['heads']:
        raise ValueError('Attention width must be divisible by heads')
    if any(config['training'][key] <= 0 for key in ('epochs', 'batch_size', 'learning_rate', 'patience')):
        raise ValueError('Training budget must be positive')
    if not 1 <= config['search']['states_per_episode'] <= config['rounds'] or config['search']['temperature'] <= 0:
        raise ValueError('Invalid search state count or temperature')
    if config['improvement_iterations'] < 0 or min(config['gp_stddev'], config['stat_stddev']) < 0:
        raise ValueError('Iterations and stress deviations cannot be negative')
    for section in ('episodes', 'improvement_episodes', 'evaluation_runs'):
        if any(value < 1 for value in config[section].values()):
            raise ValueError('Episode counts must be positive')
    if hardware:
        import torch
        from web.backend.services.draft_ml.v7_network import resolve_device
        device = resolve_device(config['training']['device'])
        # Real matrix operation, not just device discovery.
        x = torch.ones((32, 32), device=device)
        assert float((x @ x).sum()) == 32768
        audit.update({'torch': torch.__version__, 'device': device,
                      'gpu': torch.cuda.get_device_name(0) if device == 'cuda' else None})
    return audit


def fingerprint(config):
    snapshot, teacher, _ = paths(config)
    source = list((ROOT / 'web/backend/services').rglob('*.py')) + list((ROOT / 'core').rglob('*.py'))
    source += [Path(__file__), snapshot, teacher / 'genomes.json', teacher / 'manifest.json']
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for path in sorted(source):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def plan(config):
    n0 = sum(config['episodes'].values())
    ni = sum(config['improvement_episodes'].values())
    search = config['search']
    branches = search['states_per_episode'] * search['candidates'] * search['rollouts']
    return {'status': 'prepared_not_started', 'audit': preflight(config), 'config': config,
            'initial_drafts': n0, 'initial_states': n0 * config['rounds'],
            'improvement_drafts_per_iteration': ni,
            'counterfactual_continuations_per_iteration': ni * branches,
            'evaluation_full_continuations_per_scenario': 2 * branches,
            'evaluation_value_leaf_continuations_per_scenario': 2 * branches,
            'phases': ['V7.0 imitation/value', 'validation readiness gate', 'V7.1 counterfactual improvement', 'V7.2 iterative self-play with historical checkpoints', 'freeze using validation', 'new-seed paired holdout'],
            'readiness_gate': {'top1_agreement_min': .65, 'student_vs_teacher_category_delta_min': -.15},
            'estimate': {'initial_phase_hours': [4, 12], 'full_research_hours': [24, 72], 'confidence': 'low until first episode and epoch timings'},
            'resume': 'episode / epoch / evaluation scenario / stage', 'auto_promote': False}


@contextmanager
def lock(path):
    import msvcrt
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def phase(config, name, provenance):
    from web.backend.services.draft_ml.v7_data import generate
    from web.backend.services.draft_ml.v7_train import fit
    from web.backend.services.draft_ml.v7_evaluate import evaluate
    snapshot, teacher, out = paths(config)
    genomes = out / 'teacher.json'
    operation, raw_iteration = name.split(':')
    iteration = int(raw_iteration)
    current = out / f'iteration-{iteration}'
    previous = out / f'iteration-{iteration - 1}/training/best.pt' if iteration else None
    if operation == 'generate':
        generate(config, snapshot, genomes, current / 'data', iteration, provenance, previous)
    elif operation == 'train':
        fit(config, current / 'data', current / 'training', provenance, previous,
            out / 'iteration-0/data' if iteration else None)
    elif operation == 'validate':
        evaluate(config, snapshot, genomes, current / 'training/best.pt', current / 'validation', 'validation', provenance)
    elif operation == 'holdout':
        evaluate(config, snapshot, genomes, current / 'training/best.pt', out / 'holdout', 'holdout', provenance)
    else:
        raise ValueError('Unknown stage')


def run_stage(config_path, name, out, provenance):
    env = dict(os.environ)
    for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        env[key] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    log = out / 'logs' / (name.replace(':', '-') + '.log')
    log.parent.mkdir(exist_ok=True)
    started = time.monotonic()
    with log.open('a', encoding='utf-8') as handle:
        process = subprocess.Popen([sys.executable, '-u', str(Path(__file__)), '--config', str(config_path), '--stage', name, '--provenance', provenance], cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    lines = log.read_text(encoding='utf-8', errors='replace').splitlines()
                    detail = lines[-1][-200:] if lines else 'initializing'
                    print(f'{name}: {(time.monotonic()-started)/60:.1f} min | {detail}', flush=True)
        except BaseException:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], check=False, capture_output=True)
                process.wait()
            raise
    if process.returncode:
        raise RuntimeError(f'{name} failed. Saved progress retained. Log: {log}')


def stage_artifacts(name, out):
    operation, index = name.split(':')
    root = out / f'iteration-{index}'
    if operation == 'generate':
        files = [root / 'data/complete.json', *sorted((root / 'data').glob('*/*.npz'))]
    elif operation == 'train':
        files = [root / 'training/complete.json', root / 'training/best.pt']
    elif operation == 'validate':
        files = [root / 'validation/summary.json']
    else:
        files = [out / 'holdout/summary.json']
    return {str(path.relative_to(out)): sha(path) for path in files}


def execute(config, config_path):
    audit = preflight(config, hardware=True)
    _, teacher, out = paths(config)
    out.mkdir(parents=True, exist_ok=True)
    digest = fingerprint(config)
    with lock(out / 'run.lock'):
        state_path = out / 'run-state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'provenance': digest, 'completed': [], 'artifacts': {}}
        if state['provenance'] != digest:
            raise ValueError('Code/config/input changed; existing run preserved')
        atomic_json(out / 'plan.json', {**plan(config), 'hardware': audit})
        atomic_json(out / 'teacher.json', unique_teacher(json.loads((teacher / 'genomes.json').read_text(encoding='utf-8'))))
        atomic_json(state_path, state)
        def run(name):
            if name in state['completed']:
                if stage_artifacts(name, out) != state['artifacts'][name]:
                    raise ValueError('Completed stage artifact changed: ' + name)
                print('SKIP ' + name, flush=True); return
            print('START ' + name, flush=True)
            run_stage(config_path, name, out, digest)
            state['completed'].append(name)
            state['artifacts'][name] = stage_artifacts(name, out)
            atomic_json(state_path, state)
        for iteration in range(config['improvement_iterations'] + 1):
            for op in ('generate', 'train'):
                run(f'{op}:{iteration}')
            if iteration == 0:
                training = json.loads((out / 'iteration-0/training/complete.json').read_text())
                best = min(training['history'], key=lambda r: r['loss'])
                if best['top1_agreement'] < .65:
                    atomic_json(out / 'readiness-gate.json', {'passed': False, 'agreement': best['top1_agreement'], 'reason': 'Imitation agreement too low; expensive evaluation and self-play have not started.'})
                    print('STOP: imitation readiness gate failed.', flush=True)
                    return
            run(f'validate:{iteration}')
            if iteration == 0:
                validation = json.loads((out / 'iteration-0/validation/summary.json').read_text())
                delta = validation['comparisons']['student_vs_teacher']['categories']['delta']
                if delta < -.15:
                    atomic_json(out / 'readiness-gate.json', {'passed': False, 'agreement': best['top1_agreement'], 'delta': delta, 'reason': 'Imitation not ready; further expensive stages stopped for review.'})
                    print('STOP: V7.0 readiness gate failed. Review readiness-gate.json.', flush=True)
                    return
                atomic_json(out / 'readiness-gate.json', {'passed': True, 'agreement': best['top1_agreement'], 'delta': delta})
        candidates = []
        for iteration in range(config['improvement_iterations'] + 1):
            validation = json.loads((out / f'iteration-{iteration}/validation/summary.json').read_text())
            comparison = validation['comparisons']['student_vs_teacher']
            candidates.append((comparison['categories']['delta'] + .35 * comparison['top4']['delta'], iteration))
        selected = max(candidates)[1]
        selection_path = out / 'frozen-selection.json'
        selection = {'iteration': selected, 'selection': 'validation only', 'provenance': digest,
                     'checkpoint_sha256': sha(out / f'iteration-{selected}/training/best.pt')}
        if selection_path.exists() and json.loads(selection_path.read_text()) != selection:
            raise ValueError('Frozen selection differs; do not reuse an opened holdout')
        atomic_json(selection_path, selection)
        run(f'holdout:{selected}')
        atomic_json(out / 'summary.json', {'selected_iteration': selected, 'research_only': True,
                    'holdout': json.loads((out / 'holdout/summary.json').read_text())})
        print('COMPLETE V7 research. Results: ' + str(out / 'summary.json'), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--stage')
    parser.add_argument('--provenance')
    args = parser.parse_args(argv)
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if args.stage:
        if args.provenance != fingerprint(config):
            raise ValueError('Internal stage provenance mismatch')
        phase(config, args.stage, args.provenance)
    elif args.execute:
        execute(config, args.config.resolve())
    elif args.preflight:
        print(json.dumps(preflight(config, hardware=True), indent=2))
    else:
        print(json.dumps(plan(config), indent=2))


if __name__ == '__main__':
    main()
