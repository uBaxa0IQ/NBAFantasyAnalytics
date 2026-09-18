"""Cross-market non-ML experiment: fixed opponents, different hero beliefs."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from statistics import fmean
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from web.backend.services.draft_benchmark import _draft_once, _scenario, _identity, prepare_benchmark_market, _ci95

BELIEFS=('current','no_adp_boards','league_rank_only')
WORLDS=('current_mixed','league_ranking','draft_ranking','adp')


def rank_view(players,categories,mode):
    rows=prepare_benchmark_market(deepcopy(players),categories,'conservative')
    if mode=='current':
        return rows
    for p in rows:
        if mode=='no_adp_boards':
            rank=p.get('market_roto_rank') or p['category_roto_rank']
        elif mode=='league_rank_only':
            rank=p.get('espn_league_rater_rank') if p.get('market_category_match') else p['category_roto_rank']
        else:
            raise ValueError(mode)
        p['espn_market_pick']=float(rank)
        p['market_roto_rank']=rank
        p['benchmark_roto_rank']=rank
        # Zero implicit fallbacks: the hero sees no ADP or global draft rank.
        p['espn_adp']=None
        if mode=='league_rank_only':
            p['espn_roto_rank']=None
    return rows


def one_scenario(args):
    snapshot,world,slot,run=args
    os.environ['DRAFT_DISABLE_LEARNED']='1'
    players,categories,slots=snapshot['players'],snapshot['categories'],snapshot['roster_slots']
    if world=='league_ranking':
        truth=rank_view(players,categories,'league_rank_only')
    elif world=='draft_ranking':
        truth=prepare_benchmark_market(players,categories,'espn_draft')
        for p in truth:
            p['espn_market_pick']=float(p.get('espn_roto_rank') or p['category_roto_rank'])
            p['benchmark_roto_rank']=p['espn_market_pick']
    else:
        truth=rank_view(players,categories,'current')
    if world=='adp':
        for p in truth:
            p['espn_market_pick']=float(p.get('espn_adp') or p.get('market_roto_rank') or p['category_roto_rank'])
    seed=2609507+slot*1009
    market,opponent_rank=_scenario(truth,seed,run)
    profiles={s:{'policy':'adp' if world=='adp' or world=='current_mixed' and s%2==0 else 'roto','punts':()} for s in range(1,11)}
    results={}
    for belief in BELIEFS:
        perceived=rank_view(players,categories,belief)
        own_market,_=_scenario(perceived,seed,run)
        result=_draft_once(truth,slot,10,13,{'policy':'adaptive_heuristic','punts':()},market,opponent_rank,
            slots,categories,include_roster=True,opponent_profiles=profiles,
            evaluation_noise_seed=f'{seed}:{run}',hero_market_players=perceived,hero_market=own_market)
        results[belief]={'category_wins':result['category_wins'],'league_rank':result['league_rank'],
                         'roster':[_identity(p) for p in result['roster']]}
    return {'world':world,'slot':slot,'run':run,'results':results}


def summarize(rows):
    worlds={}
    for world in WORLDS:
        subset=sorted((r for r in rows if r['world']==world),key=lambda r:(r['slot'],r['run']))
        if not subset:
            continue
        worlds[world]={}
        for belief in BELIEFS:
            delta=[r['results'][belief]['category_wins']-r['results']['current']['category_wins'] for r in subset]
            worlds[world][belief]={'mean_categories':fmean(r['results'][belief]['category_wins'] for r in subset),
                'mean_rank':fmean(r['results'][belief]['league_rank'] for r in subset),'delta':fmean(delta),
                'ci95':_ci95(delta),'n':len(delta),
                'changed_rosters':sum(r['results'][belief]['roster']!=r['results']['current']['roster'] for r in subset)}
    return worlds


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--runs',type=int,default=5)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts/draft_ml/rank-only-comparison.json')
    args=parser.parse_args()
    if not args.execute:
        print(json.dumps({'dry_run':True,'drafts':len(WORLDS)*10*args.runs*len(BELIEFS),'ml':False}))
        return
    if args.runs < 1 or args.workers < 1:
        raise ValueError('runs and workers must be positive')
    if args.output.exists():
        raise FileExistsError(args.output)
    source=ROOT/'artifacts/draft_ml/standard8/standard8-market-v3-inputs.json'
    snapshot=json.loads(source.read_text(encoding='utf-8'))
    jobs=[(snapshot,w,s,r) for w in WORLDS for s in range(1,11) for r in range(args.runs)]
    rows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(one_scenario,job) for job in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows)%10==0:
                print(f'Completed paired scenarios {len(rows)}/{len(jobs)}',flush=True)
    report={'ml':False,'snapshot':str(source),'snapshot_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'design':'Fixed opponent behavior per world; only hero market perception changes. Same seeds/stats/slots.',
        'rater_missing':sum(not p.get('market_category_match') for p in snapshot['players']),
        'caveat':'League-rater API default period unverified; missing ranks use synthetic category Z. One 8-cat snapshot, not historical validation.',
        'summary':summarize(rows),'paired_outcomes':sorted(rows,key=lambda r:(r['world'],r['slot'],r['run']))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
