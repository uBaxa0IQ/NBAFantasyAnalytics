"""V8.2.4 measurement-only audit of rollout-label reliability."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED,ProcessPoolExecutor,wait
from copy import deepcopy
import hashlib,json,os,subprocess,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import torch

from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha

CONFIG=ROOT/'configs/draft_ml_v824_audit.json';CTX=None


def configuration():
    settings=json.loads(CONFIG.read_text(encoding='utf-8'));return settings,ROOT/settings['output']


def audit_formats():
    source=v81.configuration()[1]['formats'];result=[deepcopy(case) for case in source]
    ten_categories=['FG%','3PM','3PT%','REB','AST','A/TO','STL','BLK','DD','PTS']
    for case in source:
        if len(case['categories'])!=11:continue
        derived=deepcopy(case);derived['id']=case['id'].replace('c11-','c10-audit-')
        derived['categories']=ten_categories;derived['reverse']=[];result.append(derived)
    return sorted(result,key=lambda case:(len(case['categories']),case['team_count'],case['id']))


def state_indices(team_count,count):
    return [int(round(index*(team_count-1)/(count-1))) for index in range(count)] if count>1 else[team_count//2]


def fingerprint():
    settings,_=configuration();digest=hashlib.sha256(json.dumps(settings,sort_keys=True).encode())
    paths=(Path(__file__),CONFIG,ROOT/'scripts/draft_v82_auto_strategy.py',ROOT/'scripts/draft_v81_multiformat.py',
           ROOT/'configs/draft_ml_v81.json',ROOT/'web/backend/services/draft_ml/v8_state.py',
           ROOT/'web/backend/services/draft_ml/v8_network.py',ROOT/settings['champion'],ROOT/settings['snapshot'])
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize():
    global CTX
    settings,_=configuration();v81.initialize(str(ROOT/settings['champion']));v82.CTX={'settings':settings,'strategy':None}
    CTX={'settings':settings}


def finish_draws(state,hero,opponents,key,profile,rollout):
    v82.apply_profile(state,profile)
    while not state.complete:
        if state.slot==hero:action=v81.network_order(state,v81.CTX[3]['v81'])[0][0]
        else:action=v81.heuristic_action(state,opponents[state.slot]['weights'],f'{key}:r{rollout}',opponents[state.slot])
        state.apply(action)
    return np.stack([state.targets(hero,f'{key}:r{rollout}:t{draw}',.12,.08)
                     for draw in range(CTX['settings']['terminal_draws'])]).astype(np.float32)


def atomic_npz(path,**payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('wb')as handle:np.savez_compressed(handle,**payload)
    os.replace(temporary,path)


def audit_profile(job):
    case,index,profile_index,profile,path,expected=job
    state,hero,opponents,key=v82.starting_state(case,index,'v824_label_reliability')
    outcomes=[];utilities=[]
    for rollout in range(CTX['settings']['audit_rollouts']):
        draws=finish_draws(state.clone(),hero,opponents,key,tuple(profile),rollout);outcomes.append(draws)
        utilities.append([v82.outcome_utility(draw,len(case['categories'])) for draw in draws])
    atomic_npz(path,outcomes=np.stack(outcomes),utilities=np.asarray(utilities,np.float32),
               profile=np.asarray(json.dumps(profile)),profile_index=np.asarray(profile_index),scenario=np.asarray(key),
               format_id=np.asarray(case['id']),category_count=np.asarray(len(case['categories'])),
               team_count=np.asarray(case['team_count']),state_index=np.asarray(index),provenance=np.asarray(expected))
    return str(path)


def enumerate_states(settings,out,expected):
    manifests=[];jobs=[];existing=0
    for case in audit_formats():
        for index in state_indices(case['team_count'],settings['states_per_format']):
            state,_,_,key=v82.starting_state(case,index,'v824_label_reliability')
            profiles=[list(profile) for profile in v82.shortlist(state,case,settings)]
            if len(profiles)!=settings['shortlist'] or profiles[0]!=[]:raise ValueError(f'Unexpected shortlist: {case["id"]}:{index}')
            state_id=f"{case['id']}-seat{index%case['team_count']+1:02d}-state{index:03d}"
            directory=out/'raw'/state_id
            manifest={'state_id':state_id,'format_id':case['id'],'category_count':len(case['categories']),
                      'team_count':case['team_count'],'state_index':index,'scenario':key,'profiles':profiles,
                      'rollouts':settings['audit_rollouts'],'terminal_draws':settings['terminal_draws'],'provenance':expected}
            save(directory/'manifest.json',manifest);manifests.append(manifest)
            for profile_index,profile in enumerate(profiles):
                path=directory/f'profile-{profile_index:02d}.npz'
                if path.exists():
                    with np.load(path,allow_pickle=False)as data:
                        valid=str(data['provenance'])==expected and str(data['scenario'])==key and \
                              int(data['profile_index'])==profile_index and json.loads(str(data['profile']))==profile and \
                              data['utilities'].shape==(settings['audit_rollouts'],settings['terminal_draws'])
                    if not valid:raise ValueError(f'Incompatible V8.2.4 shard: {path}')
                    existing+=1
                else:jobs.append((case,index,profile_index,profile,str(path),expected))
    return manifests,jobs,existing


def parallel(settings,jobs,out,total,existing):
    started=time.monotonic();done=0
    with ProcessPoolExecutor(max_workers=settings['workers'],initializer=initialize)as pool:
        pending={pool.submit(audit_profile,job) for job in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready:future.result();done+=1
            elapsed=time.monotonic()-started
            save(out/'stage-progress.json',{'stage':'generate','completed':existing+done,'total':total,
                 'eta_seconds':elapsed/done*(len(jobs)-done) if done else None})


def ranks(values):
    order=np.argsort(values,kind='stable');result=np.empty(len(values),dtype=np.float64);result[order]=np.arange(len(values))
    return result


def state_reliability(out,manifest):
    directory=out/'raw'/manifest['state_id'];profiles=manifest['profiles'];rows=[]
    for profile_index in range(len(profiles)):
        with np.load(directory/f'profile-{profile_index:02d}.npz',allow_pickle=False)as data:rows.append(data['utilities'].copy())
    utilities=np.stack(rows).mean(2);half=utilities.shape[1]//2
    first=utilities[:,:half].mean(1);second=utilities[:,half:].mean(1);full=utilities.mean(1)
    first_rank=ranks(first);second_rank=ranks(second)
    spearman=float(np.corrcoef(first_rank,second_rank)[0,1]) if first_rank.std() and second_rank.std() else 0.
    first_best=int(first.argmax());second_best=int(second.argmax());full_best=int(full.argmax());no_punt=profiles.index([])
    first_top=set(np.argsort(first)[-3:]);second_top=set(np.argsort(second)[-3:])
    cross_regrets=[float(second.max()-second[first_best]),float(first.max()-first[second_best])]
    cross_gains=[float(second[first_best]-second[no_punt]),float(first[second_best]-first[no_punt])]
    sign_rows=[]
    for profile_index in range(len(profiles)):
        if profile_index==no_punt:continue
        sign_rows.append(bool((first[profile_index]-first[no_punt])*(second[profile_index]-second[no_punt])>0))
    paired=utilities[full_best]-utilities[no_punt];margin=1.96*float(paired.std(ddof=1))/np.sqrt(len(paired))
    sorted_full=np.sort(full)
    return {**{key:manifest[key] for key in ('state_id','format_id','category_count','team_count','state_index')},
      'spearman':spearman,'top1_agreement':first_best==second_best,'top3_overlap':len(first_top&second_top),
      'cross_regrets':cross_regrets,'cross_selected_positive':[gain>0 for gain in cross_gains],
      'profile_sign_agreement':float(np.mean(sign_rows)),'full_best_profile':profiles[full_best],
      'full_best_gain':float(full[full_best]-full[no_punt]),'full_top_second_gap':float(sorted_full[-1]-sorted_full[-2]),
      'best_vs_no_punt_interval':[float(paired.mean()-margin),float(paired.mean()+margin)],
      'best_vs_no_punt_resolved':float(paired.mean()-margin)>0}


def aggregate(rows):
    return {'states':len(rows),'median_spearman':float(np.median([row['spearman'] for row in rows])),
      'mean_spearman':float(np.mean([row['spearman'] for row in rows])),
      'top1_agreement':float(np.mean([row['top1_agreement'] for row in rows])),
      'top3_overlap_two':float(np.mean([row['top3_overlap']>=2 for row in rows])),
      'mean_top3_overlap':float(np.mean([row['top3_overlap'] for row in rows])),
      'cross_selected_positive':float(np.mean([value for row in rows for value in row['cross_selected_positive']])),
      'mean_cross_regret':float(np.mean([value for row in rows for value in row['cross_regrets']])),
      'p90_cross_regret':float(np.quantile([value for row in rows for value in row['cross_regrets']],.9)),
      'mean_profile_sign_agreement':float(np.mean([row['profile_sign_agreement'] for row in rows])),
      'resolved_best_vs_no_punt':float(np.mean([row['best_vs_no_punt_resolved'] for row in rows])),
      'median_best_gain':float(np.median([row['full_best_gain'] for row in rows])),
      'median_top_second_gap':float(np.median([row['full_top_second_gap'] for row in rows]))}


def analyze(settings,out,expected):
    complete=json.loads((out/'raw/complete.json').read_text(encoding='utf-8'))
    if complete['provenance']!=expected:raise ValueError('V8.2.4 raw-data provenance mismatch')
    rows=[state_reliability(out,manifest) for manifest in complete['manifests']]
    overall=aggregate(rows);by_family={str(count):aggregate([row for row in rows if row['category_count']==count])
                                      for count in sorted({row['category_count'] for row in rows})}
    gates=settings['reliability_gates'];checks={
      'median_spearman':overall['median_spearman']>=gates['median_spearman_min'],
      'top3_overlap_two':overall['top3_overlap_two']>=gates['top3_overlap_two_min'],
      'cross_selected_positive':overall['cross_selected_positive']>=gates['cross_selected_positive_min'],
      'mean_cross_regret':overall['mean_cross_regret']<=gates['mean_cross_regret_max']}
    passed=all(checks.values())
    summary={'passed':passed,'checks':checks,'gates':gates,'overall':overall,'by_category_count':by_family,
             'states':rows,'provenance':expected,
             'next_action':'build_adaptive_distributional_dataset' if passed else 'increase_label_precision_before_training'}
    save(out/'summary.json',summary);return summary


def phase(stage,expected):
    if fingerprint()!=expected:raise ValueError('V8.2.4 fingerprint changed')
    settings,out=configuration()
    if stage=='generate':
        manifests,jobs,existing=enumerate_states(settings,out,expected);total=len(manifests)*settings['shortlist']
        parallel(settings,jobs,out,total,existing)
        save(out/'raw/complete.json',{'provenance':expected,'states':len(manifests),'profiles':total,
             'draft_continuations':total*settings['audit_rollouts'],'terminal_outcomes':total*settings['audit_rollouts']*settings['terminal_draws'],
             'new_profiles':len(jobs),'manifests':manifests})
    else:analyze(settings,out,expected)


def plan():
    settings,out=configuration();formats=audit_formats();states=len(formats)*settings['states_per_format'];profiles=states*settings['shortlist']
    payload=torch.load(ROOT/settings['champion'],map_location='cpu',weights_only=True)
    if payload['spec'].get('architecture')!='universal_residual_v1':raise ValueError('V8.1.1 champion required')
    return {'status':'PREPARED_NOT_STARTED','experiment':'V8.2.4 rollout-label reliability audit','training':False,
      'formats':len(formats),'families':sorted({len(case['categories']) for case in formats}),'states':states,
      'profiles_per_state':settings['shortlist'],'profile_shards':profiles,
      'draft_continuations':profiles*settings['audit_rollouts'],
      'terminal_outcomes':profiles*settings['audit_rollouts']*settings['terminal_draws'],
      'half_split_rollouts':settings['audit_rollouts']//2,'workers':settings['workers'],
      'hours':{'generation':[5,12],'analysis':[.02,.1],'total':[5,12]},'output':str(out),'auto_promote':False}


def run():
    prepared=plan();expected=fingerprint();_,out=configuration();out.mkdir(parents=True,exist_ok=True)
    with lock(out/'run.lock'):
        journal_path=out/'run-state.json';journal=json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else{'provenance':expected,'completed':[]}
        if journal['provenance']!=expected:raise ValueError('Incompatible V8.2.4 resume')
        save(out/'plan.json',prepared)
        def status(name,error=None):save(out/'status.json',{'pid':os.getpid(),'phase':name,'completed':len(journal['completed']),
             'total':2,'provenance':expected,'error':error,'updated_at':time.time(),'training':False})
        child=None
        try:
            for stage in ('generate','analyze'):
                if stage in journal['completed']:continue
                status('RUNNING:'+stage)
                with(out/f'{stage}.log').open('a',encoding='utf-8')as handle:
                    child=subprocess.Popen([sys.executable,'-u',str(Path(__file__)),'--stage',stage,'--provenance',expected],
                                           cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
                    while child.poll()is None:
                        try:child.wait(timeout=15)
                        except subprocess.TimeoutExpired:status('RUNNING:'+stage)
                if child.returncode:raise RuntimeError(f'{stage} failed; progress retained')
                journal['completed'].append(stage);save(journal_path,journal)
            status('COMPLETE')
        except BaseException as exc:
            if child is not None and child.poll()is None:subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
            status('FAILED',''.join(traceback.format_exception_only(type(exc),exc)).strip());raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true')
    parser.add_argument('--stage',choices=('generate','analyze'));parser.add_argument('--provenance');args=parser.parse_args()
    if args.stage:initialize();phase(args.stage,args.provenance)
    elif args.execute:run()
    else:print(json.dumps(plan(),indent=2))
