"""Frozen full-draft late-search confirmation. No training or promotion."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts import draft_v73_diagnostic as base
from web.backend.services.draft_ml.v7_data import atomic_json
from web.backend.services.draft_ml.v7_state import State
from scripts.draft_ml_v7_run import lock, preflight

OUTPUT = ROOT / 'artifacts/draft_ml/standard8-v74-late-search'
SETTINGS = {**base.SETTINGS, 'seed': 740909, 'episodes_per_arena': 100,
            'late_picks': 4, 'terminal_draws': 8}
ARENAS = ('strong', 'mixed')
MODES = ('teacher', 'student', 'teacher_late', 'student_late')


def late_action(state, hero, arena, assignments, seed, settings):
    ids = base.candidates(state, arena, settings)[2]
    outcomes = {}
    for candidate in ids:
        outcomes[candidate] = []
        for rollout in range(settings['large_rollouts']):
            branch = state.clone()
            branch.apply(candidate)
            outcomes[candidate].append(arena.finish(branch, hero, assignments,
                f'{seed}:selection:{state.pick}:{rollout}'))
    return base.choose(ids, outcomes), len(ids) * settings['large_rollouts']


def episode(job):
    name, index = job
    config, settings, payload, arena = base.CTX
    seed = f"v74:{settings['seed']}:{name}:{index}"
    hero = index % config['team_count'] + 1
    assignments = base.assignments_for(arena, name, seed)
    results, timings, counts = {}, {}, {}
    for mode in MODES:
        started = time.monotonic()
        state = State(payload['players'], payload['roster_slots'], config['team_count'], config['rounds'])
        branches, searched, search_seconds = 0, 0, 0.
        while not state.complete:
            if state.slot != hero:
                action = arena.opponent_action(state, assignments, seed + ':actual-draft')
            elif mode.endswith('_late') and len(state.rosters[hero]) >= config['rounds'] - settings['late_picks']:
                before = time.monotonic()
                action, n = late_action(state, hero, arena, assignments, seed, settings)
                search_seconds += time.monotonic() - before
                searched += 1; branches += n
            else:
                action = arena.order(state, arena.history[2] if mode.startswith('student') else None)[0][0]
            state.apply(action)
        # Separate terminal uncertainty draws, never used during selection.
        targets = [state.targets(hero, f'{seed}:terminal-audit:{i}', config['gp_stddev'], config['stat_stddev'])
                   for i in range(settings['terminal_draws'])]
        results[mode] = np.mean(targets, axis=0).tolist()
        timings[mode] = dict(total_seconds=time.monotonic()-started, search_seconds=search_seconds)
        counts[mode] = dict(search_picks=searched, continuations=branches)
    return dict(arena=name, episode=index, hero=hero, scenario=seed,
                results=results, timings=timings, counts=counts)


def report(rows):
    def interval(values, z=1.96):
        a = np.array(values, dtype=float)
        delta = float(a.mean())
        margin = float(z*a.std(ddof=1)/np.sqrt(len(a))) if len(a)>1 else None
        return dict(delta=delta, interval=[delta-margin, delta+margin] if margin is not None else None,
                    n_drafts=len(a))
    def comparison(group, left, right, z=1.96):
        a = np.array([r['results'][left] for r in group])
        b = np.array([r['results'][right] for r in group])
        return dict(categories=interval(a[:,:8].sum(1)-b[:,:8].sum(1),z),
                    rank_gain=interval((b[:,8]-a[:,8])*9,z),
                    top4=interval(a[:,9]-b[:,9],z),top1=interval(a[:,10]-b[:,10],z))
    primary = {m+'_vs_'+m.removesuffix('_late'): comparison(rows,m,m.removesuffix('_late'),2.2414027276)
               for m in ('teacher_late','student_late')}
    arenas = {}
    for name in ARENAS:
        group = [r for r in rows if r['arena']==name]
        if not group:
            continue
        absolute = {}
        for mode in MODES:
            a = np.array([r['results'][mode] for r in group])
            absolute[mode] = dict(categories=float(a[:,:8].sum(1).mean()),rank=float(1+9*a[:,8].mean()),
                top4=float(a[:,9].mean()),top1=float(a[:,10].mean()),
                mean_draft_seconds=float(np.mean([r['timings'][mode]['total_seconds'] for r in group])),
                mean_search_pick_seconds=float(np.mean([r['timings'][mode]['search_seconds']/max(1,r['counts'][mode]['search_picks']) for r in group])))
        comparisons = {left+'_vs_'+right:comparison(group,left,right) for left,right in (
            ('student','teacher'),('teacher_late','teacher'),('student_late','student'),('student_late','teacher_late'))}
        arenas[name] = dict(absolute=absolute,comparisons_95_exploratory=comparisons)
    return dict(primary_pooled=primary,arenas=arenas,decision='STOP_FOR_USER_REVIEW_NO_TRAINING',
        interpretation=dict(primary='Two category contrasts, 97.5% marginal intervals (Bonferroni family 5%). Other metrics exploratory.',
            practical_category_target=.10,rank_noninferiority_margin=.10,top4_noninferiority_margin=.02,
            note='Targets are predeclared review criteria, not an automatic promotion rule; inconclusive results are allowed.'),
        limitations=['Same historical 8-cat, 10-team snapshot; 8 terminal draws are averaged per draft, not counted as independent drafts.',
            'Search knows fixed simulated opponent policies, an optimistic capability test, not a deployment-ready human prediction model.',
            'All search branches use a common V6.3 continuation; actual late-search arms replan at each of the last four picks.',
            'No retraining, no weekly H2H, no model selection using this sample, no automatic promotion.'])


def provenance(config):
    h=hashlib.sha256(base.digest(config,SETTINGS).encode())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()


def run():
    config=json.loads((ROOT/'configs/draft_ml_v7.json').read_text())
    preflight(config)
    digest=provenance(config)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    with lock(OUTPUT/'run.lock'):
        status_path=OUTPUT/'status.json'
        if status_path.exists() and json.loads(status_path.read_text())['provenance']!=digest:
            raise ValueError('Code/config/checkpoints changed. Existing experiment preserved.')
        rows=[]; jobs=[]
        # Interleave arenas so early timings are more representative.
        for index in range(SETTINGS['episodes_per_arena']):
            for name in ARENAS:
                path=OUTPUT/'episodes'/f'{name}-{index:04d}.json'
                if path.exists():
                    row=json.loads(path.read_text())
                    if row['provenance']!=digest or row['arena']!=name or row['episode']!=index:
                        raise ValueError('Saved scenario mismatch')
                    rows.append(row)
                else:
                    jobs.append((name,index))
        started=time.monotonic(); existing=len(rows)
        def status(phase,error=None):
            elapsed=time.monotonic()-started; done=len(rows)-existing
            atomic_json(status_path,dict(phase=phase,pid=os.getpid(),completed=len(rows),total=2*SETTINGS['episodes_per_arena'],
                elapsed_seconds=elapsed,eta_seconds=elapsed/done*(len(jobs)-done) if done else None,
                provenance=digest,updated_at=time.time(),error=error,training=False))
        atomic_json(OUTPUT/'plan.json',dict(settings=SETTINGS,arenas=ARENAS,modes=MODES,provenance=digest,
            primary='teacher_late vs teacher and student_late vs student, category score, pooled equal arenas',
            stopping='Fixed 200 scenarios. No early stopping based on results.'))
        status('RUNNING')
        pool=None
        try:
            pool=ProcessPoolExecutor(max_workers=SETTINGS['workers'],initializer=base.initialize,initargs=(config,SETTINGS))
            pending={pool.submit(episode,job) for job in jobs}
            while pending:
                ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
                for future in ready:
                    row=future.result(); row['provenance']=digest
                    atomic_json(OUTPUT/'episodes'/f"{row['arena']}-{row['episode']:04d}.json",row)
                    rows.append(row)
                status('RUNNING')
            pool.shutdown(); pool=None
            rows.sort(key=lambda r:(r['arena'],r['episode']))
            atomic_json(OUTPUT/'summary.json',{**report(rows),'provenance':digest,'settings':SETTINGS,
                'scenario_count':len(rows),'elapsed_seconds':time.monotonic()-started})
            status('COMPLETE_DIAGNOSTIC_ONLY')
        except BaseException:
            status('FAILED',traceback.format_exc())
            if pool is not None:
                pool.shutdown(wait=False,cancel_futures=True)
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    if args.execute:
        run()
    else:
        print(json.dumps(SETTINGS,indent=2))
