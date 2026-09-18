"""Plan by default. Offline v4 execution requires an explicit --execute.

No live deployment, promotion, ESPN fetch or deletion. All checkpoints/reports
are isolated from v3. A frozen input file is required and fingerprinted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web.backend.services.draft_ml.schema import TrainingConfig, categories_for_format
from web.backend.services.draft_ml.dataset import dataset_summary
from web.backend.services.draft_ml.simulation import DATASET_ENGINE_VERSION, split_for_episode


def atomic_json(path, payload):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def build_plan(snapshot, config_path, holdout=None):
    config = TrainingConfig(**json.loads(config_path.read_text(encoding='utf-8'))).validate()
    if config.format_name != 'standard8' or 'snapshot' in config.market_models:
        raise ValueError('This runner requires standard8 and explicit benchmark markets')
    inputs = json.loads(snapshot.read_text(encoding='utf-8'))
    stats_sources = Counter(str(player.get('stats_source') or 'unknown') for player in inputs.get('players', ()))
    expected = set(categories_for_format(config.format_name))
    for candidate in [inputs] + ([json.loads(holdout.read_text(encoding='utf-8'))] if holdout else []):
        if set(candidate['categories']) != expected or candidate['team_count'] != config.team_count or candidate['rounds'] != config.rounds:
            raise ValueError('Snapshot league dimensions/categories mismatch')
        if not candidate.get('players') or not candidate.get('roster_slots'):
            raise ValueError('Snapshot missing players/slots')
        if not any(p.get('market_category_match') for p in candidate['players']):
            raise ValueError('Snapshot needs league-rater provenance for the four-market comparison')
    if holdout and hashlib.sha256(snapshot.read_bytes()).digest() == hashlib.sha256(holdout.read_bytes()).digest():
        raise ValueError('Holdout must not be the training snapshot')
    out = ROOT / config.output_dir
    if not out.resolve().is_relative_to((ROOT / 'artifacts/draft_ml').resolve()):
        raise ValueError('Output directory must stay under artifacts/draft_ml')
    dataset, checkpoint = out / 'dataset.jsonl.gz', out / 'checkpoint'
    previous = ROOT / 'artifacts/draft_ml/standard8/checkpoints/standard8-market-v3'
    if not (previous / 'manifest.json').is_file():
        raise FileNotFoundError('Previous v3 checkpoint is required')
    previous_manifest = json.loads((previous / 'manifest.json').read_text(encoding='utf-8'))
    if previous_manifest.get('metadata', {}).get('format') != 'standard8':
        raise ValueError('Previous checkpoint format mismatch')
    common = ['-m', 'web.backend.services.draft_ml']
    stages = []
    def stage(name, command, output):
        stages.append({'name': name, 'args': common + command + ['--execute'], 'output': str(output)})
    stage('generate', ['generate','--config',str(config_path),'--input-snapshot',str(snapshot),
          '--output',str(dataset),'--resume'], Path(str(dataset)+'.manifest.json'))
    stage('train', ['train','--format','standard8','--dataset',str(dataset),'--checkpoint',str(checkpoint),'--seed','260904'], checkpoint/'manifest.json')
    for split in ['validation','test']:
        stage(split, ['evaluate','--dataset',str(dataset),'--checkpoint',str(checkpoint),
                     '--split',split,'--output',str(out/f'{split}.json')], out/f'{split}.json')
    snapshots = [('control', snapshot)] + ([('holdout', holdout)] if holdout else [])
    for label, evaluation_snapshot in snapshots:
        for market in config.market_models:
            for field in config.opponent_fields:
                for model, model_path in [('new',checkpoint),('previous',previous)]:
                    name = f'{label}-{market}-{field}-{model}'
                    report = out / f'{name}.json'
                    stage(name, ['benchmark','--format','standard8','--checkpoint',str(model_path),
                          '--input-snapshot',str(evaluation_snapshot),'--market-model',market,
                          '--opponent-field',field,'--seed','2609407','--runs-per-slot','10',
                          '--output',str(report)], report)
    splits = Counter(split_for_episode(config, i) for i in range(config.episodes))
    # Measured v3: 236m48s generation / 240 episodes, four reports in 27m31s.
    generation_hours = (236 + 48/60) / 60 * config.episodes/240 * config.candidate_count/8 * config.rollouts_per_candidate/3 * 8/config.workers
    benchmark_hours = (27 + 31/60) / 60 / 4 * (len(stages)-4)
    return {'status':'prepared_not_started','config':config.to_dict(),'snapshot':str(snapshot),
            'holdout':str(holdout) if holdout else None,'output_dir':str(out),
            'dataset':str(dataset),'checkpoint':str(checkpoint),'previous_checkpoint':str(previous),
            'maximum_rows':config.episodes*config.rounds*config.candidate_count,
            'episode_splits':dict(splits), 'independent_season_validation':False,
            'stats_source_counts':dict(stats_sources),
            'live_promotion_eligible':bool(stats_sources.get('selected_period', 0)),
            'time_estimate':{'generation_hours_linear':round(generation_hours,2),
              'benchmark_hours_linear':round(benchmark_hours,2),'train_test_budget_hours':0.17,
              'total_hours_linear':round(generation_hours+benchmark_hours+0.17,2),
              'planning_range_hours':[10,14] if not holdout else [12,18],
              'caveat':'Extrapolation, not a new speed test. New sampling/clone cost and CPU load are not measured.'},
            'stages':stages}


def fingerprint(plan, config_path):
    paths = [Path(plan['snapshot']), config_path, Path(__file__)]
    if plan['holdout']:
        paths.append(Path(plan['holdout']))
    paths += sorted((ROOT/'core').glob('*.py'))
    paths += sorted((ROOT/'web/backend').rglob('*.py'))
    paths += sorted(Path(plan['previous_checkpoint']).glob('*'))
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode())
    for path in paths:
        if path.is_file():
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_stage_artifact(stage, plan):
    """Reject corrupt/stale outputs instead of silently skipping them on resume."""
    name, output = stage['name'], Path(stage['output'])
    if not output.is_file():
        raise ValueError(f'Completed stage output is missing: {name}')
    payload = json.loads(output.read_text(encoding='utf-8'))
    if name == 'generate':
        dataset = Path(plan['dataset'])
        if (payload.get('engine_version') != DATASET_ENGINE_VERSION
                or payload.get('dataset_sha256') != file_sha256(dataset)
                or dataset_summary(dataset)['states'] != plan['config']['episodes'] * plan['config']['rounds']):
            raise ValueError('Generated dataset/manifest failed integrity validation')
    elif name == 'train':
        checkpoint = Path(plan['checkpoint'])
        if payload.get('metadata', {}).get('format') != 'standard8':
            raise ValueError('Checkpoint format mismatch')
        if payload.get('dataset_sha256') != file_sha256(plan['dataset']):
            raise ValueError('Checkpoint was trained on a different dataset')
        hashes = payload.get('artifact_sha256') or {}
        expected_artifacts = {'vectorizer.joblib', 'policy.joblib',
                              'value_expected_category_wins.joblib', 'value_expected_league_rank.joblib',
                              'value_downside.joblib', 'value_reward.joblib'}
        if set(hashes) != expected_artifacts:
            raise ValueError('Checkpoint artifact manifest is incomplete')
        for artifact, digest in hashes.items():
            if file_sha256(checkpoint / artifact) != digest:
                raise ValueError(f'Checkpoint artifact checksum mismatch: {artifact}')
    elif name in {'validation', 'test'}:
        provenance = payload.get('_provenance') or {}
        if (provenance.get('checkpoint') != str(Path(plan['checkpoint']).resolve())
                or provenance.get('split') != name
                or provenance.get('dataset_sha256') != file_sha256(plan['dataset'])):
            raise ValueError(f'Stale evaluation report: {name}')
    else:
        provenance = payload.get('_provenance') or {}
        parts = name.rsplit('-', 3)
        if len(parts) != 4:
            raise ValueError(f'Unexpected benchmark stage name: {name}')
        label, market, field, model = parts
        expected_checkpoint = plan['checkpoint'] if model == 'new' else plan['previous_checkpoint']
        expected_snapshot = plan['snapshot'] if label == 'control' else plan['holdout']
        if (provenance.get('checkpoint') != str(Path(expected_checkpoint).resolve())
                or provenance.get('market_model') != market
                or provenance.get('opponent_field') != field
                or provenance.get('seed') != 2609407
                or provenance.get('input_sha256') != file_sha256(expected_snapshot)
                or provenance.get('checkpoint_manifest_sha256')
                    != file_sha256(Path(expected_checkpoint) / 'manifest.json')):
            raise ValueError(f'Stale benchmark report: {name}')
    return True


@contextmanager
def run_lock(path):
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def summarize(plan):
    from statistics import fmean
    from web.backend.services.draft_benchmark import _ci95
    rows = []
    for stage in plan['stages']:
        if not stage['name'].endswith('-new'):
            continue
        new = json.loads(Path(stage['output']).read_text(encoding='utf-8'))
        old = json.loads(Path(stage['output'].replace('-new.json','-previous.json')).read_text(encoding='utf-8'))
        a, b = new['paired_outcomes']['adaptive'], old['paired_outcomes']['adaptive']
        if len(a) != len(b):
            raise ValueError('Unpaired previous/new reports')
        delta = [x['category_wins']-y['category_wins'] for x,y in zip(a,b)]
        rows.append({'scenario':stage['name'][:-4],
                     'new_vs_previous':{'delta':fmean(delta),'ci95':_ci95(delta)},
                     'new_vs_heuristic':new['comparisons_to_adaptive_heuristic']})
    return {'manual_review_required':True, 'auto_promote':False, 'comparisons':rows}


def execute(plan, config_path):
    for dependency in ['sklearn','joblib','numpy']:
        if importlib.util.find_spec(dependency) is None:
            raise RuntimeError(f'Missing {dependency}; install requirements-ml.txt first')
    out = Path(plan['output_dir'])
    out.mkdir(parents=True, exist_ok=True)
    with run_lock(out/'run.lock'):
        digest = fingerprint(plan, config_path)
        journal = out/'run-state.json'
        state = json.loads(journal.read_text()) if journal.exists() else {'fingerprint':digest,'completed':[]}
        if state['fingerprint'] != digest:
            raise ValueError('Code/config/input changed: do not mix this run with another version; journal preserved')
        atomic_json(journal,state)
        atomic_json(out/'plan.json',plan)
        env = dict(os.environ)
        env.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONUNBUFFERED','DRAFT_ML_STRICT','DRAFT_DISABLE_LEARNED']})
        env.pop('DRAFT_MODEL_CHECKPOINT',None)
        logs = out/('logs-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
        logs.mkdir()
        for number, stage in enumerate(plan['stages'],1):
            name = stage['name']
            if name in state['completed'] and Path(stage['output']).exists():
                validate_stage_artifact(stage, plan)
                print(f'{number}/{len(plan["stages"])} SKIP completed {name}',flush=True)
                continue
            # A crash after saving a full checkpoint but before marking the stage
            # should not retrain it. Incomplete checkpoint directories are backed up.
            if name == 'train' and Path(stage['output']).exists():
                validate_stage_artifact(stage, plan)
                state['completed'].append(name); atomic_json(journal,state)
                continue
            if name == 'train' and Path(plan['checkpoint']).exists():
                partial=Path(plan['checkpoint'])
                partial.rename(partial.with_name('checkpoint-incomplete-'+datetime.now().strftime('%Y%m%d-%H%M%S')))
            print(f'{number}/{len(plan["stages"])} START {name}',flush=True)
            start=time.monotonic()
            with (logs/f'{name}.log').open('w',encoding='utf-8') as output:
                process=subprocess.Popen([sys.executable]+stage['args'],cwd=ROOT,env=env,stdout=output,stderr=subprocess.STDOUT)
                try:
                    while True:
                        try:
                            code=process.wait(timeout=30); break
                        except subprocess.TimeoutExpired:
                            progress=Path(plan['dataset']+'.progress.json')
                            detail=''
                            if name=='generate' and progress.exists():
                                try:
                                    p=json.loads(progress.read_text()); detail=f' | saved {p["completed"]}/{p["total"]}'
                                except (OSError,ValueError):
                                    pass
                            print(f'{name}: {(time.monotonic()-start)/60:.1f} min{detail}',flush=True)
                except BaseException:
                    if process.poll() is None:
                        if os.name == 'nt':
                            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                        else:
                            process.terminate()
                        process.wait()
                    raise
            if code != 0:
                raise RuntimeError(f'{name} exit {code}. Saved episodes preserved. Log: {logs/name}.log')
            if not Path(stage['output']).exists():
                raise RuntimeError(f'{name} did not produce its expected output')
            state['completed'].append(name)
            atomic_json(journal,state)
            print(f'DONE {name}',flush=True)
        atomic_json(out/'summary.json',summarize(plan))
        print('COMPLETE. Reports saved. No promotion/deployment. Manual review required.',flush=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--input-snapshot',type=Path,default=ROOT/'artifacts/draft_ml/standard8/standard8-market-v4-inputs.json')
    parser.add_argument('--holdout-snapshot',type=Path)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/draft_ml_standard8_v4.json')
    args=parser.parse_args(argv)
    plan=build_plan(args.input_snapshot.resolve(),args.config.resolve(),args.holdout_snapshot.resolve() if args.holdout_snapshot else None)
    if not args.execute:
        print(json.dumps(plan,ensure_ascii=False,indent=2))
        return 0
    execute(plan,args.config.resolve())
    return 0


if __name__=='__main__':
    raise SystemExit(main())
