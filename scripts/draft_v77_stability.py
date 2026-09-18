"""Stability gate before universal architecture. No production promotion."""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from scripts import resume_v76_verified as verified
from scripts import draft_v76_distillation as d
from scripts import draft_v73_diagnostic as base
from scripts.run_v74_resilient import resilient_json as save
from scripts.draft_ml_v7_run import lock
from web.backend.services.draft_ml.v7_state import State,CATEGORIES
from web.backend.services.draft_ml.simulation import _stress_rosters

OUTPUT=ROOT/'artifacts/draft_ml/standard8-v77-stability'
SETTINGS=dict(seed=770911,training_seeds=[770912,770913],workers=6,per_condition=100,terminal_draws=8)
CONDITIONS=('strong','mixed','unseen_rules','projection_shift')
POLICIES=None


def fingerprint():
    out=verified.install(); journal=verified.check(out)
    h=hashlib.sha256(json.dumps(dict(settings=SETTINGS,old_journal=journal),sort_keys=True).encode())
    for p in (Path(__file__),ROOT/'scripts/resume_v76_verified.py',ROOT/'scripts/run_v74_resilient.py'):
        h.update(p.read_bytes())
    return h.hexdigest()


def shifted_players(players,seed):
    from core.z_score import calculate_z_scores_from_players
    changed=_stress_rosters({1:deepcopy(players)},seed,.12,.08)[1]
    for p in changed:
        p.setdefault('team_id',0); p.setdefault('team_name','')
        stats=p['stats']
        stats['3PA']=min(stats.get('3PA',0),stats.get('FGA',0))
        stats['3PM']=min(stats.get('3PM',0),stats['3PA'],stats.get('FGM',0))
        for pct,made,attempt in (('FG%','FGM','FGA'),('FT%','FTM','FTA'),('3PT%','3PM','3PA')):
            stats[pct]=stats.get(made,0)/stats[attempt] if stats.get(attempt,0)>0 else 0.
    scored=calculate_z_scores_from_players(changed,categories=CATEGORIES,reverse_categories=[])['players']
    for player,row in zip(changed,scored):
        player['z_scores']=row['z_scores']
    return changed


def rule_action(state,arena,seed):
    # New synthetic policies absent from the training opponent set.
    if state.slot%2:
        ranked=arena.order(state)
        return random.Random(f'{seed}:pick:{state.pick}').choice(ranked[:5])[0]
    roster=state.context().roster
    needs={c:1/(1+math.exp(max(-20,min(20,sum(p.get('z_scores',{}).get(c,0) for p in roster)/3)))) for c in CATEGORIES}
    return max(state.legal(),key=lambda i:sum(needs[c]*state.players[i].get('z_scores',{}).get(c,0) for c in CATEGORIES))


def initialize():
    global POLICIES
    verified.install()
    config,settings,_=d.configuration(); config['seed']=SETTINGS['seed']
    base.initialize(config,settings)
    from web.backend.services.draft_ml.v7_network import NeuralPolicy
    POLICIES={'old':base.CTX[3].history[2], 'v76':NeuralPolicy(ROOT/'artifacts/draft_ml/standard8-v76-distillation/training/best.pt')}
    for i in range(2): POLICIES[f'repeat{i+1}']=NeuralPolicy(OUTPUT/f'repeat-{i}/best.pt')


def episode(job):
    condition,index=job
    config,settings,payload,arena=base.CTX
    seed=f'v77:{SETTINGS["seed"]}:{condition}:{index}'; hero=index%10+1
    players=shifted_players(payload['players'],seed+':inputs') if condition=='projection_shift' else payload['players']
    assignments=base.assignments_for(arena,'mixed' if condition=='mixed' else 'strong',seed)
    results={}; times={}
    for mode,policy in POLICIES.items():
        started=time.monotonic(); state=State(players,payload['roster_slots'],10,13)
        while not state.complete:
            if state.slot==hero: action=arena.order(state,policy)[0][0]
            elif condition=='unseen_rules': action=rule_action(state,arena,seed)
            else: action=arena.opponent_action(state,assignments,seed+':actual')
            state.apply(action)
        results[mode]=np.mean([state.targets(hero,f'{seed}:terminal:{i}',config['gp_stddev'],config['stat_stddev']) for i in range(SETTINGS['terminal_draws'])],axis=0).tolist()
        times[mode]=time.monotonic()-started
    return dict(condition=condition,episode=index,scenario=seed,results=results,seconds=times)


def report(rows):
    def compare(group,mode,baseline='old',z=1.96):
        a=np.array([r['results'][mode] for r in group]); b=np.array([r['results'][baseline] for r in group])
        values=dict(categories=a[:,:8].sum(1)-b[:,:8].sum(1),rank_gain=9*(b[:,8]-a[:,8]),top4=a[:,9]-b[:,9],top1=a[:,10]-b[:,10])
        result={}
        for k,v in values.items():
            mean=float(v.mean()); margin=float(z*v.std(ddof=1)/np.sqrt(len(v))) if len(v)>1 else None
            result[k]=dict(delta=mean,interval=[mean-margin,mean+margin] if margin is not None else None,n_drafts=len(v))
        return result
    conditions={}
    for name in CONDITIONS:
        group=[r for r in rows if r['condition']==name]
        if group: conditions[name]={mode:compare(group,mode) for mode in ('v76','repeat1','repeat2')}
    return dict(primary_pooled={mode:compare(rows,mode,z=2.3939798) for mode in ('v76','repeat1','repeat2')},by_condition=conditions,
        decision='STOP_BEFORE_UNIVERSAL_ARCHITECTURE',limitations=[
            'Three predeclared category contrasts use 98.333% marginal intervals (Bonferroni); other metrics exploratory.',
            'Only two additional optimization seeds on the SAME frozen dataset, not independent dataset regenerations.',
            'Novel synthetic rules are not all human behavior. Projection shift recomputes input Z scores, but is not a new historical season.',
            'Still 8 categories, 10 teams. Universal architecture is not trained or launched by this script.',
            'All trained replicas are reported, no best-seed selection or automatic promotion.'])


def train(index,digest):
    from web.backend.services.draft_ml import v7_train as t
    config,_,source=d.configuration(); config['seed']=SETTINGS['training_seeds'][index]
    t.atomic_json=save
    original=t.atomic_torch
    def checkpoint(path,payload):
        for attempt in range(21):
            try: original(path,payload); return
            except PermissionError:
                if attempt==20: raise
                time.sleep(.5)
    t.atomic_torch=checkpoint
    t.fit(config,source/'data',OUTPUT/f'repeat-{index}',digest,warm_start=d.OLD)


def evaluate(digest):
    rows=[]; jobs=[]
    for index in range(SETTINGS['per_condition']):
        for condition in CONDITIONS:
            path=OUTPUT/'episodes'/f'{condition}-{index:04d}.json'
            if path.exists():
                row=json.loads(path.read_text())
                if row['provenance']!=digest or row['condition']!=condition or row['episode']!=index: raise ValueError('Saved scenario mismatch')
                rows.append(row)
            else: jobs.append((condition,index))
    started=time.monotonic(); existing=len(rows)
    with ProcessPoolExecutor(max_workers=6,initializer=initialize) as pool:
        pending={pool.submit(episode,job) for job in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready:
                row=future.result(); row['provenance']=digest
                save(OUTPUT/'episodes'/f"{row['condition']}-{row['episode']:04d}.json",row); rows.append(row)
            done=len(rows)-existing; elapsed=time.monotonic()-started
            save(OUTPUT/'stage-progress.json',dict(stage='evaluate',completed=len(rows),total=400,eta_seconds=elapsed/done*(len(jobs)-done) if done else None))
    rows.sort(key=lambda r:(r['condition'],r['episode']))
    save(OUTPUT/'summary.json',{**report(rows),'provenance':digest,'scenario_count':len(rows)})


def run():
    digest=fingerprint(); OUTPUT.mkdir(parents=True,exist_ok=True)
    with lock(OUTPUT/'run.lock'):
        journal_path=OUTPUT/'run-state.json'
        journal=json.loads(journal_path.read_text()) if journal_path.exists() else dict(provenance=digest,completed=[],checksums={})
        if journal['provenance']!=digest: raise ValueError('Incompatible run')
        save(OUTPUT/'plan.json',dict(settings=SETTINGS,conditions=CONDITIONS,provenance=digest,stopping='Report every seed, then stop. No universal-model launch.'))
        def status(phase,error=None): save(OUTPUT/'status.json',dict(pid=os.getpid(),phase=phase,completed=len(journal['completed']),total=3,provenance=digest,error=error,updated_at=time.time()))
        def checks(stage):
            paths=[OUTPUT/f'repeat-{stage[-1]}/best.pt',OUTPUT/f'repeat-{stage[-1]}/complete.json'] if stage.startswith('train') else [OUTPUT/'summary.json']
            return {str(p.relative_to(OUTPUT)):d.sha(p) for p in paths}
        try:
            for stage in ('train0','train1','evaluate'):
                if stage in journal['completed']:
                    if checks(stage)!=journal['checksums'][stage]: raise ValueError('Completed output changed')
                    continue
                status('RUNNING:'+stage)
                with (OUTPUT/f'{stage}.log').open('a',encoding='utf-8') as handle:
                    child=subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'--stage',stage,'--provenance',digest],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
                    try:
                        while child.poll() is None:
                            try: child.wait(timeout=15)
                            except subprocess.TimeoutExpired: status('RUNNING:'+stage)
                    except BaseException:
                        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True); raise
                if child.returncode: raise RuntimeError(f'{stage} failed, saved progress retained')
                journal['completed'].append(stage); journal['checksums'][stage]=checks(stage); save(journal_path,journal)
            status('COMPLETE')
        except BaseException: status('FAILED',traceback.format_exc()); raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--execute',action='store_true'); parser.add_argument('--stage',choices=['train0','train1','evaluate']); parser.add_argument('--provenance')
    args=parser.parse_args()
    if args.stage:
        if fingerprint()!=args.provenance: raise ValueError('Stage mismatch')
        train(int(args.stage[-1]),args.provenance) if args.stage.startswith('train') else evaluate(args.provenance)
    elif args.execute: run()
    else: print(json.dumps(dict(settings=SETTINGS,conditions=CONDITIONS,verified_provenance=fingerprint(),estimated_hours=[2,4],started=False),indent=2))
