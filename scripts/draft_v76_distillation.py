"""Late-search distillation. Dry by default; explicit launch required."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from scripts import draft_v73_diagnostic as base
from scripts import draft_v75_unknown_search as blind
from scripts.run_v74_resilient import resilient_json as save
from scripts.draft_ml_v7_run import lock, preflight
from web.backend.services.draft_ml.v7_state import State, sha
from web.backend.services.draft_ml.v7_data import softmax, utility

CONFIG=ROOT/'configs/draft_ml_v76.json'
OLD=ROOT/'artifacts/draft_ml/standard8-v7/iteration-2/training/best.pt'
NEW=None


def configuration():
    settings=json.loads(CONFIG.read_text())
    config=json.loads((ROOT/'configs/draft_ml_v7.json').read_text())
    config.update(seed=settings['seed'],workers=settings['workers'],training=settings['training'])
    return config, {**blind.SETTINGS,**settings}, ROOT/settings['output']


def identity(config,settings):
    digest=hashlib.sha256(base.digest(config,settings).encode())
    for path in (Path(__file__),CONFIG,ROOT/'scripts/draft_v75_unknown_search.py',ROOT/'scripts/run_v74_resilient.py',ROOT/'scripts/draft_ml_v7_run.py'):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(config,settings,checkpoint=None):
    global NEW
    base.initialize(config,settings)
    NEW=None
    if checkpoint:
        from web.backend.services.draft_ml.v7_network import NeuralPolicy
        NEW=NeuralPolicy(checkpoint)


def scenario(split,index):
    return f'v76:{base.CTX[1]["seed"]}:{split}:{index}'


def improved_target(state,hero,arena,settings,key):
    logits,_=arena.history[2].predict(state)
    legal=state.legal()
    old=np.zeros(len(state.players),dtype=np.float32)
    old[legal]=softmax(logits[legal],settings['teacher_temperature'])
    baseline=max(legal,key=lambda i:float(logits[i]))
    ids=base.candidates(state,arena,settings)[2]
    selected={}
    for i in ids:
        selected[i]=[]
        for rollout in range(settings['large_rollouts']):
            seed=f'{key}:select:{rollout}'
            branch=state.clone(); branch.apply(i)
            selected[i].append(arena.finish(branch,hero,blind.prior_assignments(arena,key,rollout),seed))
    chosen=base.choose(ids,selected)
    audit={}
    for i in set((baseline,chosen)):
        samples=[]
        for rollout in range(settings['audit_rollouts']):
            seed=f'{key}:audit:{rollout}'
            branch=state.clone(); branch.apply(i)
            samples.append(arena.finish(branch,hero,blind.prior_assignments(arena,key+':audit',rollout),seed))
        audit[i]=float(np.mean([utility(x) for x in samples]))
    gain=audit[chosen]-audit[baseline]
    accepted=chosen!=baseline and gain>=settings['audit_min_utility_gain']
    target=old.copy()
    if accepted:
        # Full legal-action loss: the network must also beat unsearched players.
        search=np.zeros_like(old)
        search[ids]=softmax([utility(np.mean(selected[i],axis=0)) for i in ids],settings['search_temperature'])
        target=settings['old_policy_blend']*old+(1-settings['old_policy_blend'])*search
    return target,chosen if accepted else baseline,dict(accepted=accepted,gain=gain,baseline=baseline,chosen=chosen)


def generate_episode(job):
    split,index,path,provenance=job
    config,settings,payload,arena=base.CTX
    key=scenario(split,index); hero=index%config['team_count']+1
    name=blind.ARENAS[(index//config['team_count'])%2]
    assignments=base.assignments_for(arena,name,key)
    state=State(payload['players'],payload['roster_slots'],config['team_count'],config['rounds'])
    encodings=[]; policies=[]; audits=[]
    while not state.complete:
        if state.slot!=hero:
            state.apply(arena.opponent_action(state,assignments,key+':actual')); continue
        encoded=state.encode(); logits,_=arena.history[2].predict(state)
        legal=state.legal(); policy=np.zeros(len(state.players),dtype=np.float32)
        policy[legal]=softmax(logits[legal],settings['teacher_temperature'])
        action=max(legal,key=lambda i:float(logits[i]))
        if len(state.rosters[hero])>=config['rounds']-settings['late_picks']:
            policy,action,audit=improved_target(state,hero,arena,settings,f'{key}:pick:{state.pick}')
            audits.append(audit)
        encodings.append(encoded); policies.append(policy); state.apply(action)
    targets=np.mean([state.targets(hero,f'{key}:terminal:{i}',config['gp_stddev'],config['stat_stddev']) for i in range(settings['terminal_draws'])],axis=0)
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    with temp.open('wb') as handle:
        np.savez_compressed(handle,tokens=np.stack([e[0] for e in encodings]),roles=np.stack([e[1] for e in encodings]),
            global_state=np.stack([e[2] for e in encodings]),legal=np.stack([e[3] for e in encodings]),
            loss_mask=np.stack([e[3] for e in encodings]),policy=np.stack(policies),
            value=np.repeat(targets[None],len(policies),axis=0),scenario=np.asarray(key),provenance=np.asarray(provenance),
            audits=np.asarray(json.dumps(audits)))
    replace_retry(temp,path)
    return dict(split=split,index=index,accepted=sum(x['accepted'] for x in audits),searched=len(audits))


def replace_retry(temp,path):
    for attempt in range(21):
        try: os.replace(temp,path); return
        except PermissionError:
            if attempt==20: raise
            time.sleep(min(.05*(attempt+1),.5))


def cheap_action(state,hero,arena,policy,settings,key):
    own=[i for i,_ in arena.order(state,policy)]
    teacher=[i for i,_ in arena.order(state)]
    ids=list(dict.fromkeys(own[:2]+teacher[:2]+base.candidates(state,arena,settings)[2]))[:settings['cheap_candidates']]
    values={}
    for i in ids:
        values[i]=[]
        for rollout in range(settings['cheap_rollouts']):
            branch=state.clone(); branch.apply(i)
            values[i].append(arena.finish(branch,hero,blind.prior_assignments(arena,key,rollout),f'{key}:draw:{rollout}'))
    return base.choose(ids,values)


def evaluate_episode(job):
    split,name,index=job
    config,settings,payload,arena=base.CTX
    key=scenario('evaluation-'+split+':'+name,index); hero=index%config['team_count']+1
    assignments=base.assignments_for(arena,name,key)
    results={}; timings={}
    for mode in ('old','new','old_cheap','new_cheap'):
        policy=NEW if mode.startswith('new') else arena.history[2]
        state=State(payload['players'],payload['roster_slots'],config['team_count'],config['rounds'])
        start=time.monotonic()
        while not state.complete:
            if state.slot!=hero: action=arena.opponent_action(state,assignments,key+':actual')
            elif mode.endswith('cheap') and len(state.rosters[hero])>=config['rounds']-settings['late_picks']:
                action=cheap_action(state,hero,arena,policy,settings,f'{key}:blind:{state.pick}')
            else: action=arena.order(state,policy)[0][0]
            state.apply(action)
        results[mode]=np.mean([state.targets(hero,f'{key}:terminal:{i}',config['gp_stddev'],config['stat_stddev']) for i in range(settings['terminal_draws'])],axis=0).tolist()
        timings[mode]=time.monotonic()-start
    return dict(split=split,arena=name,episode=index,scenario=key,results=results,timings=timings)


def report(rows):
    def compare(group,left,right,z):
        a=np.array([r['results'][left] for r in group]); b=np.array([r['results'][right] for r in group])
        values=dict(categories=a[:,:8].sum(1)-b[:,:8].sum(1),rank_gain=9*(b[:,8]-a[:,8]),top4=a[:,9]-b[:,9],top1=a[:,10]-b[:,10])
        result={}
        for key,v in values.items():
            mean=float(v.mean()); error=float(z*v.std(ddof=1)/np.sqrt(len(v))) if len(v)>1 else None
            result[key]=dict(delta=mean,interval=[mean-error,mean+error] if error is not None else None,n=len(v))
        return result
    primary={a+'_vs_'+b:compare(rows,a,b,2.2414027276) for a,b in (('new','old'),('new_cheap','old_cheap'))}
    return dict(primary=primary,secondary={a+'_vs_'+b:compare(rows,a,b,1.96) for a,b in (('new','old_cheap'),('new_cheap','new'))},
        by_arena={name:{a+'_vs_'+b:compare([r for r in rows if r['arena']==name],a,b,1.96) for a,b in (('new','old'),('new_cheap','old_cheap'))} for name in blind.ARENAS if any(r['arena']==name for r in rows)},
        n_drafts=len(rows),limitations=['Two primary category contrasts use 97.5% Bonferroni intervals; remaining analyses exploratory.',
            'Same historical 8-cat/10-team snapshot and familiar policy families. No real-season guarantee or production promotion.'])


def parallel_jobs(config,settings,jobs,worker,consume,out,stage,checkpoint=None):
    start=time.monotonic(); completed=0
    with ProcessPoolExecutor(max_workers=settings['workers'],initializer=initialize,initargs=(config,settings,checkpoint)) as pool:
        pending={pool.submit(worker,job) for job in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready: consume(future.result()); completed+=1
            save(out/'stage-progress.json',dict(stage=stage,completed=completed,total=len(jobs),elapsed_seconds=time.monotonic()-start))


def phase(name,expected):
    config,settings,out=configuration()
    if identity(config,settings)!=expected: raise ValueError('Stage code/input mismatch')
    if name=='generate':
        jobs=[]
        for split,count in settings['episodes'].items():
            for index in range(count):
                path=out/'data'/split/f'{index:06d}.npz'
                if path.exists():
                    with np.load(path,allow_pickle=False) as data:
                        if str(data['provenance'])!=expected or str(data['scenario'])!=f'v76:{settings["seed"]}:{split}:{index}': raise ValueError('Saved data mismatch')
                else: jobs.append((split,index,str(path),expected))
        parallel_jobs(config,settings,jobs,generate_episode,lambda row:None,out,name)
        accepted=searched=training_accepted=0
        for path in (out/'data').glob('*/*.npz'):
            with np.load(path,allow_pickle=False) as data:
                audits=json.loads(str(data['audits'])); accepted+=sum(x['accepted'] for x in audits); searched+=len(audits)
                if path.parent.name=='train': training_accepted+=sum(x['accepted'] for x in audits)
        save(out/'data/complete.json',dict(provenance=expected,accepted=accepted,searched=searched,training_accepted=training_accepted))
    elif name=='train':
        from web.backend.services.draft_ml import v7_train as training
        training.atomic_json=save
        original=training.atomic_torch
        def checkpoint_write(path,payload):
            for attempt in range(21):
                try: original(path,payload); return
                except PermissionError:
                    if attempt==20: raise
                    time.sleep(.5)
        training.atomic_torch=checkpoint_write
        training.fit(config,out/'data',out/'training',expected,warm_start=OLD)
    else:
        checkpoint=out/'training/best.pt'; rows=[]; jobs=[]
        for index in range(settings['evaluation'][name]//2):
            for arena in blind.ARENAS:
                path=out/name/f'{arena}-{index:04d}.json'
                if path.exists():
                    row=json.loads(path.read_text())
                    if row['provenance']!=expected or row['checkpoint_sha256']!=sha(checkpoint): raise ValueError('Evaluation mismatch')
                    rows.append(row)
                else: jobs.append((name,arena,index))
        def consume(row):
            row.update(provenance=expected,checkpoint_sha256=sha(checkpoint)); rows.append(row)
            save(out/name/f"{row['arena']}-{row['episode']:04d}.json",row)
        parallel_jobs(config,settings,jobs,evaluate_episode,consume,out,name,str(checkpoint))
        rows.sort(key=lambda r:(r['arena'],r['episode']))
        save(out/name/'summary.json',{**report(rows),'provenance':expected,'checkpoint_sha256':sha(checkpoint)})


def plan():
    config,settings,out=configuration(); audit=preflight(config,hardware=True)
    if any(n<=0 or n%20 for n in (*settings['episodes'].values(),*settings['evaluation'].values())): raise ValueError('Counts must be positive multiples of 20 for arena/seat balance')
    if not OLD.exists(): raise ValueError('Missing old checkpoint')
    return dict(status='PREPARED_NOT_STARTED',audit=audit,settings=settings,output=str(out),
        data_drafts=sum(settings['episodes'].values()),late_decisions=4*sum(settings['episodes'].values()),
        evaluation_drafts=sum(settings['evaluation'].values()),hours=dict(generation=[9,14],training=[.3,1.5],validation=[1,2],holdout=[2,3.5],total=[13,21]),
        estimate_basis='V7.5 ~93 seconds/full search pick and ~25 seconds/cheap pick under 6 workers; generation adds an independent audit.',
        auto_promote=False,training_requires_explicit_execute=True)


def run():
    config,settings,out=configuration(); prepared=plan(); digest=identity(config,settings)
    out.mkdir(parents=True,exist_ok=True)
    with lock(out/'run.lock'):
        journal_path=out/'run-state.json'
        journal=json.loads(journal_path.read_text()) if journal_path.exists() else dict(provenance=digest,completed=[],checksums={})
        if journal['provenance']!=digest: raise ValueError('Incompatible resume')
        save(out/'plan.json',prepared)
        def status(phase_name,error=None): save(out/'status.json',dict(pid=os.getpid(),phase=phase_name,completed=len(journal['completed']),total=4,provenance=digest,error=error,updated_at=time.time(),training=True))
        def checks(name):
            paths=list((out/'data').glob('*/*.npz'))+[out/'data/complete.json'] if name=='generate' else ([out/'training/best.pt',out/'training/complete.json'] if name=='train' else [out/name/'summary.json'])
            return {str(p.relative_to(out)):sha(p) for p in paths}
        try:
            for name in ('generate','train','validation','holdout'):
                if name=='train':
                    generated=json.loads((out/'data/complete.json').read_text())
                    if generated['training_accepted']<settings['minimum_accepted_training_picks']:
                        save(out/'gate.json',dict(passed=False,reason='Too few independently accepted training picks; training not started.',training_accepted=generated['training_accepted'])); status('STOP_FOR_REVIEW'); return
                if name=='holdout':
                    validation=json.loads((out/'validation/summary.json').read_text())
                    delta=validation['primary']['new_vs_old']['categories']['delta']
                    if delta<-.10:
                        save(out/'gate.json',dict(passed=False,reason='Validation category regression exceeds 0.10; holdout unopened',delta=delta)); status('STOP_FOR_REVIEW'); return
                    frozen=dict(checkpoint_sha256=sha(out/'training/best.pt'),provenance=digest)
                    if (out/'frozen.json').exists() and json.loads((out/'frozen.json').read_text())!=frozen: raise ValueError('Frozen checkpoint changed')
                    save(out/'frozen.json',frozen)
                if name in journal['completed']:
                    if journal['checksums'][name]!=checks(name): raise ValueError('Completed artifact changed')
                    continue
                status('RUNNING:'+name)
                log=out/f'{name}.log'
                with log.open('a',encoding='utf-8') as handle:
                    child=subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'--stage',name,'--provenance',digest],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
                    try:
                        while child.poll() is None:
                            try: child.wait(timeout=15)
                            except subprocess.TimeoutExpired: status('RUNNING:'+name)
                    except BaseException:
                        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True); raise
                if child.returncode: raise RuntimeError(f'{name} failed; see {log}')
                journal['completed'].append(name); journal['checksums'][name]=checks(name); save(journal_path,journal)
            save(out/'summary.json',dict(provenance=digest,holdout=json.loads((out/'holdout/summary.json').read_text()),decision='STOP_FOR_USER_REVIEW_NO_PROMOTION'))
            status('COMPLETE')
        except BaseException: status('FAILED',traceback.format_exc()); raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--execute',action='store_true'); parser.add_argument('--stage',choices=['generate','train','validation','holdout']); parser.add_argument('--provenance')
    args=parser.parse_args()
    if args.stage: phase(args.stage,args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(),indent=2))
