"""V8.2 automatic punt discovery: rollout teacher, strategy scorer and sealed holdout."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from itertools import combinations
import hashlib,json,os,random,subprocess,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import numpy as np
import torch

from scripts import draft_v81_multiformat as v81
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha
from web.backend.services.draft_ml.v8_state import CATEGORY_TO_ID,CATEGORY_VOCAB,UniversalState
from web.backend.services.draft_ml.v82_strategy import StrategyPolicy,fit_strategy

CONFIG=ROOT/'configs/draft_ml_v82.json'; CTX=None


def configuration():
    settings=json.loads(CONFIG.read_text()); return settings,ROOT/settings['output']


def fingerprint():
    settings,_=configuration(); digest=hashlib.sha256(json.dumps(settings,sort_keys=True).encode())
    paths=(Path(__file__),CONFIG,ROOT/'scripts/draft_v81_multiformat.py',ROOT/'web/backend/services/draft_ml/v8_state.py',
           ROOT/'web/backend/services/draft_ml/v8_network.py',ROOT/'web/backend/services/draft_ml/v82_strategy.py',
           ROOT/settings['champion'],ROOT/settings['snapshot'],ROOT/'artifacts/draft_ml/v811-residual/holdout/summary.json')
    for path in paths: digest.update(str(path.relative_to(ROOT)).encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(strategy_checkpoint=None):
    global CTX
    settings,_=configuration(); v81.initialize(str(ROOT/settings['champion']))
    CTX={'settings':settings,'strategy':StrategyPolicy(strategy_checkpoint) if strategy_checkpoint else None}


def profiles(case,settings):
    categories=tuple(case['categories']); maximum=settings['max_punts'][str(len(categories))]
    return [combo for count in range(maximum+1) for combo in combinations(categories,count)]


def weights(case,punt):
    punt=set(punt); return tuple(0.0 if category in punt else 1.0 for category in case['categories'])


def apply_profile(state,punt): state.category_weights=weights({'categories':state.categories},punt)


def starting_state(case,index,split):
    settings=CTX['settings']; key=f'v82:{settings["seed"]}:{split}:{case["id"]}:{index}'
    players=v81.case_players(case); hero=index%case['team_count']+1
    state=UniversalState(players,case['slots'],case['team_count'],categories=case['categories'],
                         reverse_categories=case.get('reverse',()),category_weights={c:1 for c in case['categories']})
    opponents=v81.opponent_assignments(case,key); commit=min(settings['commit_round'],len(case['slots'])-1)
    while not state.complete:
        if state.slot==hero and len(state.rosters[hero])>=commit: break
        if state.slot==hero: action=v81.network_order(state,v81.CTX[3]['v81'])[0][0]
        else: action=v81.heuristic_action(state,opponents[state.slot]['weights'],key,opponents[state.slot])
        state.apply(action)
    return state,hero,opponents,key


def state_features(state,case,profile):
    features=np.zeros((len(CATEGORY_VOCAB),7),np.float32); mask=np.zeros(len(CATEGORY_VOCAB),np.bool_)
    roster=[state.players[i] for i in state.rosters[state.slot]]; remaining=[state.players[i] for i in state.remaining]
    punt=set(profile)
    for category in case['categories']:
        cid=CATEGORY_TO_ID[category]; mask[cid]=True
        own=np.asarray([p.get('z_scores',{}).get(category,0) for p in roster],dtype=np.float32)
        pool=np.asarray([p.get('z_scores',{}).get(category,0) for p in remaining],dtype=np.float32)
        top=np.sort(pool)[-min(10,len(pool)):]
        features[cid]=[own.sum()/4,own.mean()/4 if len(own) else 0,top.mean()/4,pool.mean()/4,
                       pool.std()/4,0.0 if category in punt else 1.0,float(category in state.reverse_categories)]
    global_state=np.asarray([state.team_count/16,state.rounds/20,len(roster)/state.rounds,
                             len(case['categories'])/len(CATEGORY_VOCAB),len(profile)/max(1,len(case['categories']))],np.float32)
    return features,mask,global_state


def shortlist(state,case,settings):
    all_profiles=profiles(case,settings); strength={c:sum(p.get('z_scores',{}).get(c,0) for p in state.context().roster) for c in case['categories']}
    ranked=sorted(all_profiles,key=lambda p:(-sum(-strength[c] for c in p)+.08*len(p),len(p),p))
    required=[()] + [(c,) for c in case['categories']]
    return list(dict.fromkeys(required+ranked))[:min(settings['shortlist'],len(all_profiles))]


def outcome_utility(target,count):
    return float(np.mean(target[:count])+.05*(1-target[count])+.02*target[count+1]+.02*target[count+2])


def finish(state,hero,opponents,key,profile,rollout):
    apply_profile(state,profile)
    while not state.complete:
        if state.slot==hero: action=v81.network_order(state,v81.CTX[3]['v81'])[0][0]
        else: action=v81.heuristic_action(state,opponents[state.slot]['weights'],f'{key}:r{rollout}',opponents[state.slot])
        state.apply(action)
    settings=CTX['settings']
    return np.mean([state.targets(hero,f'{key}:r{rollout}:t{draw}',.12,.08) for draw in range(settings['terminal_draws'])],axis=0)


def label_episode(job):
    split,case,index,path,provenance=job; settings=CTX['settings']; state,hero,opponents,key=starting_state(case,index,split)
    candidates=shortlist(state,case,settings); feature_rows=[]; masks=[]; globals_=[]; utilities=[]
    for profile in candidates:
        f,m,g=state_features(state,case,profile); feature_rows.append(f); masks.append(m); globals_.append(g)
        samples=[finish(state.clone(),hero,opponents,key,profile,r) for r in range(settings['label_rollouts'])]
        utilities.append(outcome_utility(np.mean(samples,axis=0),len(case['categories'])))
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as handle: np.savez_compressed(handle,features=np.stack(feature_rows),masks=np.stack(masks),
        globals=np.stack(globals_),utilities=np.asarray(utilities,np.float32),profiles=np.asarray(json.dumps(candidates)),
        scenario=np.asarray(key),format_id=np.asarray(case['id']),provenance=np.asarray(provenance))
    os.replace(temporary,path)
    best=candidates[int(np.argmax(utilities))]
    return {'format_id':case['id'],'best':best,'gain':max(utilities)-utilities[candidates.index(())]}


def choose_strategy(state,case):
    candidates=profiles(case,CTX['settings']); rows=[state_features(state,case,p) for p in candidates]
    scores=CTX['strategy'].scores(np.stack([r[0] for r in rows]),np.stack([r[1] for r in rows]),np.stack([r[2] for r in rows]))
    return candidates[int(np.argmax(scores))]


def evaluation_episode(job):
    split,case,index=job; settings=CTX['settings']; results={}; selected={}
    for mode in ('balanced','auto'):
        state,hero,opponents,key=starting_state(case,index,split); profile=() if mode=='balanced' else choose_strategy(state,case)
        target=finish(state,hero,opponents,key,profile,0); results[mode]=target.tolist(); selected[mode]=profile
    return {'split':split,'format_id':case['id'],'episode':index,'scenario':key,'categories':case['categories'],
            'team_count':case['team_count'],'results':results,'selected':selected}


def report(rows):
    overall=v81.metric(rows,'auto','balanced',2.2414027276)
    return {'primary':{'auto_vs_balanced':overall},
        'by_format':{fid:v81.metric([r for r in rows if r['format_id']==fid],'auto','balanced') for fid in sorted({r['format_id'] for r in rows})},
        'selection_counts':{fid:{str(tuple(p)):sum(tuple(r['selected']['auto'])==tuple(p) for r in rows if r['format_id']==fid)
                                 for p in sorted({tuple(r['selected']['auto']) for r in rows if r['format_id']==fid})}
                            for fid in sorted({r['format_id'] for r in rows})},'n_drafts':len(rows)}


def parallel(jobs,worker,consume,checkpoint,out,stage,total,existing=0):
    started=time.monotonic();done=0
    with ProcessPoolExecutor(max_workers=CTX['settings']['workers'],initializer=initialize,initargs=(checkpoint,)) as pool:
        pending={pool.submit(worker,j) for j in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready: consume(future.result());done+=1
            elapsed=time.monotonic()-started; save(out/'stage-progress.json',{'stage':stage,'completed':existing+done,'total':total,
                'eta_seconds':elapsed/done*(len(jobs)-done) if done else None})


def phase(stage,expected):
    if fingerprint()!=expected: raise ValueError('V8.2 fingerprint changed')
    settings,out=configuration(); cases=v81.configuration()[1]['formats']; holdout_cases=v81.configuration()[1]['holdout_formats']
    if stage=='generate':
        jobs=[];total=0
        for split,count_key in (('train','train_states_per_format'),('validation','validation_states_per_format')):
            for case in cases:
                for index in range(settings[count_key]):
                    total+=1; path=out/'data'/split/f"{case['id']}-{index:04d}.npz"
                    if path.exists():
                        with np.load(path,allow_pickle=False) as data:
                            wanted=f'v82:{settings["seed"]}:{split}:{case["id"]}:{index}'
                            if str(data['provenance'])!=expected or str(data['scenario'])!=wanted:
                                raise ValueError(f'Incompatible strategy shard: {path}')
                    else: jobs.append((split,case,index,str(path),expected))
        stats=[]; parallel(jobs,label_episode,stats.append,None,out,stage,total,total-len(jobs))
        save(out/'data/complete.json',{'provenance':expected,'shards':total,'new_shards':len(jobs),'rows':stats})
    elif stage=='train': fit_strategy(settings,out/'data',out/'training',expected)
    else:
        split=stage; active=cases if split=='validation_eval' else holdout_cases
        cycles=settings['validation_cycles_per_seat'] if split=='validation_eval' else settings['holdout_cycles_per_seat']
        checkpoint=out/'training/best.pt';rows=[];jobs=[];total=sum(c['team_count']*cycles for c in active)
        for case in active:
            for index in range(case['team_count']*cycles):
                path=out/split/f"{case['id']}-{index:05d}.json"
                if path.exists():
                    row=json.loads(path.read_text())
                    if row['provenance']!=expected or row['checkpoint_sha256']!=sha(checkpoint):
                        raise ValueError(f'Incompatible V8.2 evaluation row: {path}')
                    rows.append(row)
                else: jobs.append((split,case,index))
        def consume(row):
            row.update(provenance=expected,checkpoint_sha256=sha(checkpoint));rows.append(row)
            save(out/split/f"{row['format_id']}-{row['episode']:05d}.json",row)
        parallel(jobs,evaluation_episode,consume,str(checkpoint),out,stage,total,total-len(jobs));rows.sort(key=lambda r:(r['format_id'],r['episode']))
        summary={**report(rows),'provenance':expected,'checkpoint_sha256':sha(checkpoint)};save(out/split/'summary.json',summary)


def plan():
    settings,out=configuration(); champion=ROOT/settings['champion']; payload=torch.load(champion,map_location='cpu',weights_only=True)
    if payload['spec'].get('architecture')!='universal_residual_v1': raise ValueError('V8.1.1 champion required')
    formats=v81.configuration()[1]['formats']; holdouts=v81.configuration()[1]['holdout_formats']
    shards=len(formats)*(settings['train_states_per_format']+settings['validation_states_per_format'])
    max_profiles=max(len(profiles(c,settings)) for c in formats)
    validation=sum(c['team_count']*settings['validation_cycles_per_seat'] for c in formats)
    holdout=sum(c['team_count']*settings['holdout_cycles_per_seat'] for c in holdouts)
    return {'status':'PREPARED','strategy':'automatic rollout-distilled punt selection','fresh_2027_projections':False,
        'label_states':shards,'label_continuations_max':shards*settings['shortlist']*settings['label_rollouts'],
        'max_enumerated_profiles':max_profiles,'validation_drafts':validation,'sealed_holdout_drafts':holdout,
        'device':'cuda' if torch.cuda.is_available() else 'cpu','hours':{'generation':[2,5],'training':[.1,.5],
        'validation':[.25,1],'holdout':[.2,.7],'total':[3,7]},'output':str(out),'auto_promote':False}


def run():
    prepared=plan();expected=fingerprint();settings,out=configuration();out.mkdir(parents=True,exist_ok=True)
    with lock(out/'run.lock'):
        journal_path=out/'run-state.json';journal=json.loads(journal_path.read_text()) if journal_path.exists() else {'provenance':expected,'completed':[]}
        if journal['provenance']!=expected: raise ValueError('Incompatible V8.2 resume')
        save(out/'plan.json',prepared)
        def status(name,error=None): save(out/'status.json',{'pid':os.getpid(),'phase':name,'completed':len(journal['completed']),
            'total':4,'provenance':expected,'error':error,'updated_at':time.time(),'training':True})
        child=None
        try:
            for stage in ('generate','train','validation_eval','holdout'):
                if stage=='holdout':
                    validation=json.loads((out/'validation_eval/summary.json').read_text())['primary']['auto_vs_balanced']['normalized_categories']
                    gates=settings['validation_gates']
                    if validation['delta']<gates['normalized_delta_min'] or validation['interval'][0]<gates['interval_low_min']:
                        save(out/'gate.json',{'passed':False,'validation':validation,'gates':gates});status('STOP_FOR_REVIEW');return
                    save(out/'gate.json',{'passed':True,'validation':validation,'gates':gates})
                if stage in journal['completed']: continue
                status('RUNNING:'+stage)
                with (out/f'{stage}.log').open('a',encoding='utf-8') as handle:
                    child=subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'--stage',stage,'--provenance',expected],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
                    while child.poll() is None:
                        try: child.wait(timeout=15)
                        except subprocess.TimeoutExpired: status('RUNNING:'+stage)
                if child.returncode: raise RuntimeError(f'{stage} failed; progress retained')
                journal['completed'].append(stage);save(journal_path,journal)
            status('COMPLETE')
        except BaseException as exc:
            if child is not None and child.poll() is None: subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
            status('FAILED',''.join(traceback.format_exception_only(type(exc),exc)).strip());raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--stage',choices=('generate','train','validation_eval','holdout'));parser.add_argument('--provenance');args=parser.parse_args()
    if args.stage: initialize();phase(args.stage,args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(),indent=2))
