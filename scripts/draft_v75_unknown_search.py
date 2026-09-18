"""Frozen unknown-opponent late-search test. Never trains or promotes models."""
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
from scripts import draft_v73_diagnostic as base
from scripts import draft_v74_late_search as previous
from scripts.run_v74_resilient import resilient_json as save
from scripts.draft_ml_v7_run import lock, preflight
from web.backend.services.draft_ml.v7_state import State

OUTPUT = ROOT / 'artifacts/draft_ml/standard8-v75-unknown-search'
SETTINGS = {**previous.SETTINGS, 'seed': 750909, 'cheap_candidates': 6, 'cheap_rollouts': 3}
ARENAS = ('strong', 'mixed')
MODES = ('teacher', 'student', 'student_oracle', 'student_unknown', 'student_cheap')


def prior_assignments(arena, search_seed, rollout):
    # Crucially: no real assignments, real arena name or outer scenario seed.
    key = f'{search_seed}:prior:{rollout}'
    family = random.Random(key).choice(ARENAS)
    return base.assignments_for(arena, family, key)


def search(state, hero, arena, settings, search_seed, cheap=False, oracle=None):
    teacher, student, expanded = base.candidates(state, arena, settings)
    ids = list(dict.fromkeys(student[:2] + teacher[:2] + expanded))[:settings['cheap_candidates']] if cheap else expanded
    count = settings['cheap_rollouts'] if cheap else settings['large_rollouts']
    assignments = [oracle if oracle is not None else prior_assignments(arena, search_seed, i) for i in range(count)]
    values = {}
    for candidate in ids:
        values[candidate] = []
        for rollout, opponents in enumerate(assignments):
            branch = state.clone(); branch.apply(candidate)
            values[candidate].append(arena.finish(branch, hero, opponents, f'{search_seed}:draw:{rollout}'))
    return base.choose(ids, values), len(ids)*count


def episode(job):
    name, index = job
    config, settings, payload, arena = base.CTX
    outer = f"v75:{settings['seed']}:{name}:{index}"
    hero = index % config['team_count'] + 1
    actual = base.assignments_for(arena, name, outer)
    results, counts, timings = {}, {}, {}
    for mode in MODES:
        state = State(payload['players'], payload['roster_slots'], config['team_count'], config['rounds'])
        started=time.monotonic(); search_seconds=0.; picks=0; branches=0
        while not state.complete:
            if state.slot != hero:
                action=arena.opponent_action(state,actual,outer+':actual')
            elif mode not in ('teacher','student') and len(state.rosters[hero]) >= config['rounds']-settings['late_picks']:
                before=time.monotonic()
                # Search randomness is independent of the real arena and its seed.
                key=f"blind:{settings['seed']}:{2*index+ARENAS.index(name)}:{state.pick}"
                if mode=='student_oracle':
                    action,n=search(state,hero,arena,settings,key,oracle=actual)
                else:
                    action,n=search(state,hero,arena,settings,key,cheap=mode=='student_cheap')
                search_seconds+=time.monotonic()-before; branches+=n; picks+=1
            else:
                action=arena.order(state,None if mode=='teacher' else arena.history[2])[0][0]
            state.apply(action)
        targets=[state.targets(hero,f'{outer}:audit:{i}',config['gp_stddev'],config['stat_stddev']) for i in range(settings['terminal_draws'])]
        results[mode]=np.mean(targets,axis=0).tolist()
        counts[mode]=dict(search_picks=picks,continuations=branches)
        timings[mode]=dict(total_seconds=time.monotonic()-started,search_seconds=search_seconds)
    return dict(arena=name,episode=index,scenario=outer,hero=hero,results=results,counts=counts,timings=timings)


def report(rows):
    def compare(group,left,right,z=1.96):
        a=np.array([r['results'][left] for r in group]); b=np.array([r['results'][right] for r in group])
        values=dict(categories=a[:,:8].sum(1)-b[:,:8].sum(1),rank_gain=9*(b[:,8]-a[:,8]),top4=a[:,9]-b[:,9],top1=a[:,10]-b[:,10])
        result={}
        for key,v in values.items():
            delta=float(v.mean()); margin=float(z*v.std(ddof=1)/np.sqrt(len(v))) if len(v)>1 else None
            result[key]=dict(delta=delta,interval=[delta-margin,delta+margin] if margin is not None else None,n_drafts=len(v))
        return result
    primary={mode+'_vs_student':compare(rows,mode,'student',2.2414027276) for mode in ('student_unknown','student_cheap')}
    arenas={}
    for name in ARENAS:
        group=[r for r in rows if r['arena']==name]
        if not group: continue
        absolute={}
        for mode in MODES:
            a=np.array([r['results'][mode] for r in group])
            seconds=[r['timings'][mode]['search_seconds']/max(1,r['counts'][mode]['search_picks']) for r in group]
            absolute[mode]=dict(categories=float(a[:,:8].sum(1).mean()),rank=float(1+9*a[:,8].mean()),
                top4=float(a[:,9].mean()),top1=float(a[:,10].mean()),mean_search_pick_seconds=float(np.mean(seconds)),
                mean_continuations=float(np.mean([r['counts'][mode]['continuations'] for r in group])))
        contrasts=[('student','teacher'),('student_oracle','student'),('student_unknown','student'),
                   ('student_cheap','student'),('student_unknown','student_oracle'),('student_cheap','student_unknown')]
        arenas[name]=dict(absolute=absolute,exploratory_95={a+'_vs_'+b:compare(group,a,b) for a,b in contrasts})
    return dict(primary_pooled=primary,arenas=arenas,decision='STOP_FOR_USER_REVIEW_NO_TRAINING',
        limitations=['Search uses a fixed prior mixture of known policy families, not the actual opponent identities or arena label. Unseen human policies remain untested.',
            'Oracle arm intentionally knows actual policies and is only a reference.',
            'Two primary category comparisons have 97.5% Bonferroni intervals. Other metrics/contrasts exploratory.',
            'Eight terminal draws are averaged within each of 200 independent drafts; no weekly H2H or new-season data.',
            'Fixed historical 8-cat/10-team snapshot. Search uses common V6.3 continuations. No training or promotion.'])


def provenance(config):
    h=hashlib.sha256(base.digest(config,SETTINGS).encode())
    for p in (Path(__file__),ROOT/'scripts/draft_v74_late_search.py',ROOT/'scripts/run_v74_resilient.py'):
        h.update(p.read_bytes())
    return h.hexdigest()


def run():
    config=json.loads((ROOT/'configs/draft_ml_v7.json').read_text()); preflight(config)
    digest=provenance(config); OUTPUT.mkdir(parents=True,exist_ok=True)
    with lock(OUTPUT/'run.lock'):
        status_path=OUTPUT/'status.json'
        if status_path.exists() and json.loads(status_path.read_text())['provenance']!=digest:
            raise ValueError('Frozen inputs/code changed; refusing incompatible resume')
        rows=[]; jobs=[]
        for index in range(SETTINGS['episodes_per_arena']):
            for name in ARENAS:
                path=OUTPUT/'episodes'/f'{name}-{index:04d}.json'
                if path.exists():
                    row=json.loads(path.read_text())
                    if row['provenance']!=digest or row['arena']!=name or row['episode']!=index: raise ValueError('Saved episode mismatch')
                    rows.append(row)
                else: jobs.append((name,index))
        started=time.monotonic(); existing=len(rows)
        def status(phase,error=None):
            elapsed=time.monotonic()-started; done=len(rows)-existing
            save(status_path,dict(phase=phase,pid=os.getpid(),completed=len(rows),total=200,
                elapsed_seconds=elapsed,eta_seconds=elapsed/done*(len(jobs)-done) if done else None,
                provenance=digest,updated_at=time.time(),error=error,training=False))
        save(OUTPUT/'plan.json',dict(settings=SETTINGS,arenas=ARENAS,modes=MODES,provenance=digest,
            primary='unknown vs student and cheap vs student: pooled equal-arena category deltas, 97.5% intervals',
            practical_target=.10,stopping='Fixed 200 scenarios, then user review. No automatic training.'))
        status('RUNNING'); pool=None
        try:
            pool=ProcessPoolExecutor(max_workers=SETTINGS['workers'],initializer=base.initialize,initargs=(config,SETTINGS))
            pending={pool.submit(episode,job) for job in jobs}
            while pending:
                ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
                for future in ready:
                    row=future.result(); row['provenance']=digest
                    save(OUTPUT/'episodes'/f"{row['arena']}-{row['episode']:04d}.json",row); rows.append(row)
                status('RUNNING')
            pool.shutdown(); pool=None
            rows.sort(key=lambda r:(r['arena'],r['episode']))
            save(OUTPUT/'summary.json',{**report(rows),'provenance':digest,'settings':SETTINGS,'scenario_count':len(rows)})
            status('COMPLETE_DIAGNOSTIC_ONLY')
        except BaseException:
            status('FAILED',traceback.format_exc())
            if pool is not None: pool.shutdown(wait=False,cancel_futures=True)
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--execute',action='store_true')
    if parser.parse_args().execute: run()
    else: print(json.dumps(SETTINGS,indent=2))
