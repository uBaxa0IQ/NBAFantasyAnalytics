"""V8.2.3 family-safe calibration of the frozen V8.2.2 ensemble."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED,ProcessPoolExecutor,wait
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
from web.backend.services.draft_ml.v82_strategy import StrategyEnsembleV3

CONFIG=ROOT/'configs/draft_ml_v823.json';CTX=None


def configuration():
    settings=json.loads(CONFIG.read_text(encoding='utf-8'));return settings,ROOT/settings['output']


def checkpoint_paths(settings):
    source=ROOT/settings['source_run']
    return [source/'training'/f'seed-{seed}'/'best.pt' for seed in settings['training_seeds']]


def fingerprint():
    settings,_=configuration();digest=hashlib.sha256(json.dumps(settings,sort_keys=True).encode())
    paths=[Path(__file__),CONFIG,ROOT/'scripts/draft_v82_auto_strategy.py',
           ROOT/'web/backend/services/draft_ml/v82_strategy.py',ROOT/settings['champion'],
           ROOT/settings['source_run']/'holdout-summary.json',ROOT/settings['source_run']/'selection.json',
           *checkpoint_paths(settings)]
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def development_families(settings):
    summary=json.loads((ROOT/settings['source_run']/'holdout-summary.json').read_text(encoding='utf-8'))
    gates=settings['development_evidence_gates'];accepted=[];evidence={}
    for family,value in summary['by_category_count'].items():
        metric=value['normalized_categories'];passed=metric['delta']>=gates['normalized_delta_min'] and metric['interval'][0]>=gates['interval_low_min']
        evidence[family]={'passed':passed,'delta':metric['delta'],'interval':metric['interval'],'n_drafts':metric['n_drafts']}
        if passed:accepted.append(family)
    return sorted(accepted,key=int),evidence


def initialize(checkpoints=None,family_policies=None):
    global CTX
    settings,_=configuration();v81.initialize(str(ROOT/settings['champion']));v82.CTX={'settings':settings,'strategy':None}
    CTX={'settings':settings,'ensemble':StrategyEnsembleV3(checkpoints) if checkpoints else None,
         'family_policies':family_policies or {}}


def choose(state,case):
    confidence=CTX['family_policies'].get(str(len(case['categories'])))
    if confidence is None:return ()
    candidates=v82.profiles(case,CTX['settings']);rows=[v82.state_features(state,case,profile) for profile in candidates]
    matrix=CTX['ensemble'].score_matrix(np.stack([row[0] for row in rows]),np.stack([row[1] for row in rows]),np.stack([row[2] for row in rows]))
    mean=matrix.mean(0);winner=int(mean.argmax());votes=int((matrix.argmax(1)==winner).sum());no_punt=candidates.index(())
    if votes<confidence['minimum_votes'] or mean[winner]-mean[no_punt]<confidence['margin']:return ()
    return candidates[winner]


def episode(job):
    split,case,index=job;results={};selected={}
    for mode in ('balanced','auto'):
        state,hero,opponents,key=v82.starting_state(case,index,split)
        profile=() if mode=='balanced' else choose(state,case)
        results[mode]=v82.finish(state,hero,opponents,key,profile,0).tolist();selected[mode]=profile
    return {'split':split,'format_id':case['id'],'episode':index,'scenario':key,'categories':case['categories'],
            'team_count':case['team_count'],'results':results,'selected':selected}


def report(rows):
    counts={}
    for row in rows:
        key=str(tuple(row['selected']['auto']));counts[key]=counts.get(key,0)+1
    families={}
    for count in sorted({len(row['categories']) for row in rows}):
        subset=[row for row in rows if len(row['categories'])==count]
        families[str(count)]=v81.metric(subset,'auto','balanced')
    return {'primary':{'auto_vs_balanced':v81.metric(rows,'auto','balanced',2.2414027276)},
      'by_format':{fid:v81.metric([row for row in rows if row['format_id']==fid],'auto','balanced') for fid in sorted({row['format_id'] for row in rows})},
      'by_category_count':families,'selection_counts':counts,'unique_profiles':len(counts),
      'maximum_profile_share':max(counts.values())/len(rows),'n_drafts':len(rows)}


def parallel(settings,jobs,consume,checkpoints,policies,out,stage,total,existing=0):
    started=time.monotonic();done=0
    with ProcessPoolExecutor(max_workers=settings['workers'],initializer=initialize,initargs=(checkpoints,policies)) as pool:
        pending={pool.submit(episode,job) for job in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready:consume(future.result());done+=1
            elapsed=time.monotonic()-started
            save(out/'stage-progress.json',{'stage':stage,'completed':existing+done,'total':total,
                 'eta_seconds':elapsed/done*(len(jobs)-done) if done else None})


def evaluate(settings,out,split,cases,policies,expected,name):
    directory=out/split/name;paths=checkpoint_paths(settings);checkpoints=[str(path) for path in paths]
    checksums=[sha(path) for path in paths];validation=split=='v823_calibration_validation'
    cycles=settings['validation_cycles_per_seat'] if validation else settings['holdout_cycles_per_seat']
    rows=[];jobs=[];total=sum(case['team_count']*cycles for case in cases)
    for case in cases:
        for index in range(case['team_count']*cycles):
            path=directory/f"{case['id']}-{index:05d}.json"
            if path.exists():
                row=json.loads(path.read_text(encoding='utf-8'))
                if row['provenance']!=expected or row['checkpoint_sha256']!=checksums:raise ValueError(f'Bad V8.2.3 resume row: {path}')
                rows.append(row)
            else:jobs.append((split,case,index))
    def consume(row):
        row.update(provenance=expected,checkpoint_sha256=checksums,family_policies=policies);rows.append(row)
        save(directory/f"{row['format_id']}-{row['episode']:05d}.json",row)
    parallel(settings,jobs,consume,checkpoints,policies,out,f'{split}:{name}',total,total-len(jobs))
    rows.sort(key=lambda row:(row['format_id'],row['episode']))
    summary={**report(rows),'family_policies':policies,'provenance':expected,'checkpoint_sha256':checksums}
    save(directory/'summary.json',summary);return summary


def eligible(summary,gates):
    metric=summary['primary']['auto_vs_balanced']['normalized_categories']
    return metric['delta']>=gates['normalized_delta_min'] and metric['interval'][0]>=gates['interval_low_min'] and \
        summary['maximum_profile_share']<=gates['maximum_profile_share'] and summary['unique_profiles']>=gates['minimum_unique_profiles']


def phase(stage,expected):
    if fingerprint()!=expected:raise ValueError('V8.2.3 fingerprint changed')
    settings,out=configuration();formats=v81.configuration()[1];families,evidence=development_families(settings)
    if stage=='validation':
        selected={};audits={}
        for family in families:
            cases=[case for case in formats['formats'] if len(case['categories'])==int(family)]
            summaries=[]
            for confidence in settings['confidence_candidates']:
                name=f"c{family}-m{confidence['margin']:.1f}-v{confidence['minimum_votes']}"
                summaries.append(evaluate(settings,out,'v823_calibration_validation',cases,{family:confidence},expected,name))
            passing=[summary for summary in summaries if eligible(summary,settings['calibration_gates'])]
            compact=[{'confidence':summary['family_policies'][family],
                      'delta':summary['primary']['auto_vs_balanced']['normalized_categories']['delta'],
                      'interval':summary['primary']['auto_vs_balanced']['normalized_categories']['interval'],
                      'unique_profiles':summary['unique_profiles'],'maximum_profile_share':summary['maximum_profile_share']}
                     for summary in summaries]
            if passing:
                chosen=max(passing,key=lambda summary:summary['primary']['auto_vs_balanced']['normalized_categories']['interval'][0])
                selected[family]=chosen['family_policies'][family]
            audits[family]=compact
        save(out/'selection.json',{'passed':bool(selected),'family_policies':selected,'development_evidence':evidence,
             'calibration':audits,'gates':settings['calibration_gates'],'provenance':expected})
    else:
        selection=json.loads((out/'selection.json').read_text(encoding='utf-8'))
        if not selection['passed']:raise ValueError('V8.2.3 holdout sealed after failed calibration')
        summary=evaluate(settings,out,'v823_fresh_holdout',formats['holdout_formats'],selection['family_policies'],expected,'family-system')
        save(out/'holdout-summary.json',summary)


def plan():
    settings,out=configuration();families,evidence=development_families(settings)
    for path in checkpoint_paths(settings):
        payload=torch.load(path,map_location='cpu',weights_only=True)
        if payload['spec'].get('architecture')!='universal_strategy_v3':raise ValueError('Frozen V8.2.2 ensemble required')
    formats=v81.configuration()[1]
    validation_cases=[case for case in formats['formats'] if str(len(case['categories'])) in families]
    validation=sum(case['team_count']*settings['validation_cycles_per_seat'] for case in validation_cases)
    holdout=sum(case['team_count']*settings['holdout_cycles_per_seat'] for case in formats['holdout_formats'])
    return {'status':'PREPARED_NOT_STARTED','model':'V8.2.3 family-safe calibration','training':False,
      'frozen_v822_checkpoints':len(checkpoint_paths(settings)),'development_eligible_families':families,
      'development_evidence':evidence,'confidence_candidates':len(settings['confidence_candidates']),
      'fresh_calibration_drafts':validation*len(settings['confidence_candidates']),
      'fresh_holdout_drafts':holdout,'device':'cpu-multiprocess evaluation',
      'hours':{'calibration':[.35,.9],'holdout':[.15,.5],'total':[.5,1.4]},'output':str(out),'auto_promote':False}


def run():
    prepared=plan();expected=fingerprint();_,out=configuration();out.mkdir(parents=True,exist_ok=True)
    with lock(out/'run.lock'):
        journal_path=out/'run-state.json';journal=json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else{'provenance':expected,'completed':[]}
        if journal['provenance']!=expected:raise ValueError('Incompatible V8.2.3 resume')
        save(out/'plan.json',prepared)
        def status(name,error=None):
            save(out/'status.json',{'pid':os.getpid(),'phase':name,'completed':len(journal['completed']),'total':2,
                 'provenance':expected,'error':error,'updated_at':time.time(),'training':False})
        child=None
        try:
            for stage in ('validation','holdout'):
                if stage=='holdout' and not json.loads((out/'selection.json').read_text(encoding='utf-8'))['passed']:
                    status('STOP_FOR_REVIEW');return
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
    parser.add_argument('--stage',choices=('validation','holdout'));parser.add_argument('--provenance');args=parser.parse_args()
    if args.stage:phase(args.stage,args.provenance)
    elif args.execute:run()
    else:print(json.dumps(plan(),indent=2))
