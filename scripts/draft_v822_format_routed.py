"""V8.2.2 balanced, format-routed automatic punt controller."""
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
from web.backend.services.draft_ml.v82_strategy import StrategyEnsembleV3,fit_strategy_v3

CONFIG=ROOT/'configs/draft_ml_v822.json';CTX=None


def configuration():
    settings=json.loads(CONFIG.read_text(encoding='utf-8'));return settings,ROOT/settings['output']


def fingerprint():
    settings,_=configuration();digest=hashlib.sha256(json.dumps(settings,sort_keys=True).encode())
    paths=(Path(__file__),CONFIG,ROOT/'scripts/draft_v82_auto_strategy.py',
           ROOT/'web/backend/services/draft_ml/v82_strategy.py',ROOT/'web/backend/services/draft_ml/v8_network.py',
           ROOT/settings['champion'],ROOT/settings['source_data']/'complete.json',
           ROOT/'artifacts/draft_ml/v821-auto-strategy/selection.json')
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(checkpoints=None,confidence=None):
    global CTX
    settings,_=configuration();v81.initialize(str(ROOT/settings['champion']));v82.CTX={'settings':settings,'strategy':None}
    CTX={'settings':settings,'ensemble':StrategyEnsembleV3(checkpoints) if checkpoints else None,
         'confidence':confidence or {'margin':0.,'minimum_votes':1}}


def choose(state,case):
    candidates=v82.profiles(case,CTX['settings']);rows=[v82.state_features(state,case,p) for p in candidates]
    matrix=CTX['ensemble'].score_matrix(np.stack([r[0] for r in rows]),np.stack([r[1] for r in rows]),np.stack([r[2] for r in rows]))
    mean=matrix.mean(0);winner=int(mean.argmax());votes=int((matrix.argmax(1)==winner).sum());no_punt=candidates.index(())
    confidence=CTX['confidence']
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
      'by_format':{fid:v81.metric([r for r in rows if r['format_id']==fid],'auto','balanced') for fid in sorted({r['format_id'] for r in rows})},
      'by_category_count':families,'selection_counts':counts,'unique_profiles':len(counts),
      'maximum_profile_share':max(counts.values())/len(rows),'n_drafts':len(rows)}


def parallel(settings,jobs,consume,checkpoints,confidence,out,stage,total,existing=0):
    started=time.monotonic();done=0
    with ProcessPoolExecutor(max_workers=settings['workers'],initializer=initialize,initargs=(checkpoints,confidence)) as pool:
        pending={pool.submit(episode,job) for job in jobs}
        while pending:
            ready,pending=wait(pending,timeout=15,return_when=FIRST_COMPLETED)
            for future in ready:consume(future.result());done+=1
            elapsed=time.monotonic()-started
            save(out/'stage-progress.json',{'stage':stage,'completed':existing+done,'total':total,
                 'eta_seconds':elapsed/done*(len(jobs)-done) if done else None})


def evaluate(settings,out,split,confidence,expected):
    v81settings=v81.configuration()[1]
    validation=split=='v822_validation_eval';cases=v81settings['formats'] if validation else v81settings['holdout_formats']
    cycles=settings['validation_cycles_per_seat'] if validation else settings['holdout_cycles_per_seat']
    name=f"m{confidence['margin']:.1f}-v{confidence['minimum_votes']}";directory=out/split/name
    checkpoint_paths=[out/'training'/f'seed-{seed}'/'best.pt' for seed in settings['training_seeds']]
    checkpoints=[str(path) for path in checkpoint_paths];checksums=[sha(path) for path in checkpoint_paths]
    rows=[];jobs=[];total=sum(case['team_count']*cycles for case in cases)
    for case in cases:
        for index in range(case['team_count']*cycles):
            path=directory/f"{case['id']}-{index:05d}.json"
            if path.exists():
                row=json.loads(path.read_text(encoding='utf-8'))
                if row['provenance']!=expected or row['checkpoint_sha256']!=checksums:raise ValueError(f'Bad V8.2.2 resume row: {path}')
                rows.append(row)
            else:jobs.append((split,case,index))
    def consume(row):
        row.update(provenance=expected,checkpoint_sha256=checksums,confidence=confidence);rows.append(row)
        save(directory/f"{row['format_id']}-{row['episode']:05d}.json",row)
    parallel(settings,jobs,consume,checkpoints,confidence,out,f'{split}:{name}',total,total-len(jobs))
    rows.sort(key=lambda row:(row['format_id'],row['episode']))
    summary={**report(rows),'confidence':confidence,'provenance':expected,'checkpoint_sha256':checksums}
    save(directory/'summary.json',summary);return summary


def eligible(summary,gates):
    overall=summary['primary']['auto_vs_balanced']['normalized_categories']
    if overall['delta']<gates['normalized_delta_min'] or overall['interval'][0]<gates['interval_low_min']:return False
    if summary['maximum_profile_share']>gates['maximum_profile_share'] or summary['unique_profiles']<gates['minimum_unique_profiles']:return False
    for family,value in summary['by_category_count'].items():
        delta=value['normalized_categories']['delta']
        minimum=gates['standard8_delta_min'] if family=='8' else gates['family_delta_min']
        if delta<minimum:return False
    return True


def phase(stage,expected):
    if fingerprint()!=expected:raise ValueError('V8.2.2 fingerprint changed')
    settings,out=configuration()
    if stage=='train':
        for seed in settings['training_seeds']:
            fit_strategy_v3(settings,ROOT/settings['source_data'],out/'training'/f'seed-{seed}',expected,seed)
    elif stage=='validation':
        summaries=[evaluate(settings,out,'v822_validation_eval',candidate,expected) for candidate in settings['confidence_candidates']]
        passing=[summary for summary in summaries if eligible(summary,settings['validation_gates'])]
        compact=[{'confidence':summary['confidence'],
                  'delta':summary['primary']['auto_vs_balanced']['normalized_categories']['delta'],
                  'interval':summary['primary']['auto_vs_balanced']['normalized_categories']['interval'],
                  'family_delta':{family:value['normalized_categories']['delta'] for family,value in summary['by_category_count'].items()},
                  'unique_profiles':summary['unique_profiles'],'maximum_profile_share':summary['maximum_profile_share']}
                 for summary in summaries]
        if not passing:
            save(out/'selection.json',{'passed':False,'candidates':compact,'gates':settings['validation_gates'],'provenance':expected});return
        chosen=max(passing,key=lambda summary:summary['primary']['auto_vs_balanced']['normalized_categories']['interval'][0])
        save(out/'selection.json',{'passed':True,'confidence':chosen['confidence'],'validation':chosen['primary'],
             'family_validation':chosen['by_category_count'],'candidates':compact,'gates':settings['validation_gates'],'provenance':expected})
    else:
        selection=json.loads((out/'selection.json').read_text(encoding='utf-8'))
        if not selection['passed']:raise ValueError('V8.2.2 holdout is sealed after failed validation')
        summary=evaluate(settings,out,'v822_holdout',selection['confidence'],expected);save(out/'holdout-summary.json',summary)


def plan():
    settings,out=configuration();source=ROOT/settings['source_data'];complete=json.loads((source/'complete.json').read_text(encoding='utf-8'))
    if complete['shards']!=300:raise ValueError('Expected 300 immutable V8.2 rollout-label shards')
    payload=torch.load(ROOT/settings['champion'],map_location='cpu',weights_only=True)
    if payload['spec'].get('architecture')!='universal_residual_v1':raise ValueError('V8.1.1 champion required')
    vs=v81.configuration()[1]
    validation=sum(case['team_count']*settings['validation_cycles_per_seat'] for case in vs['formats'])
    holdout=sum(case['team_count']*settings['holdout_cycles_per_seat'] for case in vs['holdout_formats'])
    return {'status':'PREPARED_NOT_STARTED','model':'V8.2.2 format-routed balanced strategy ensemble',
      'reused_label_shards':300,'new_rollout_labels':0,'training_seeds':len(settings['training_seeds']),
      'confidence_candidates':len(settings['confidence_candidates']),'fresh_validation_split':'v822_validation_eval',
      'fresh_validation_drafts':validation*len(settings['confidence_candidates']),
      'sealed_holdout_split':'v822_holdout','sealed_holdout_drafts':holdout,
      'device':'cuda' if torch.cuda.is_available() else'cpu',
      'hours':{'training':[.6,1.5],'validation':[.8,1.8],'holdout':[.15,.5],'total':[1.7,3.8]},
      'output':str(out),'auto_promote':False}


def run():
    prepared=plan();expected=fingerprint();settings,out=configuration();out.mkdir(parents=True,exist_ok=True)
    with lock(out/'run.lock'):
        journal_path=out/'run-state.json'
        journal=json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else{'provenance':expected,'completed':[]}
        if journal['provenance']!=expected:raise ValueError('Incompatible V8.2.2 resume')
        save(out/'plan.json',prepared)
        def status(name,error=None):
            save(out/'status.json',{'pid':os.getpid(),'phase':name,'completed':len(journal['completed']),'total':3,
                 'provenance':expected,'error':error,'updated_at':time.time(),'training':True})
        child=None
        try:
            for stage in ('train','validation','holdout'):
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
            if child is not None and child.poll()is None:
                subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
            status('FAILED',''.join(traceback.format_exception_only(type(exc),exc)).strip());raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true')
    parser.add_argument('--stage',choices=('train','validation','holdout'));parser.add_argument('--provenance');args=parser.parse_args()
    if args.stage:phase(args.stage,args.provenance)
    elif args.execute:run()
    else:print(json.dumps(plan(),indent=2))
