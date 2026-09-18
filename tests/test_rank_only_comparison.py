from copy import deepcopy

from scripts.compare_rank_only import rank_view, summarize
from web.backend.services import draft_benchmark as benchmark


def test_rank_only_view_removes_adp_and_preserves_input():
    rows=[{'player_id':1,'name':'A','position':'PG','stats':{'PTS':20},
           'espn_adp':5,'espn_roto_rank':10,'espn_league_rater_rank':20,
           'espn_rater_categories':['PTS']}]
    original=deepcopy(rows)
    view=rank_view(rows,['PTS'],'league_rank_only')
    assert view[0]['espn_market_pick']==20
    assert view[0]['espn_adp'] is None
    assert view[0]['espn_roto_rank'] is None
    assert rows==original


def test_hero_beliefs_do_not_change_the_opponent_board(monkeypatch):
    rows=[{'player_id':i,'name':str(i),'espn_roto_rank':i,'stats':{'GP':1,'PTS':i}} for i in (1,2,3,4)]
    beliefs=[{**r,'espn_market_pick':100-r['player_id']} for r in rows]
    seen=[]
    def select(order,*args,**kwargs):
        seen.append(order)
        return order[0][1]
    monkeypatch.setattr(benchmark,'_select_player',select)
    result=benchmark._draft_once(rows,2,2,2,{'policy':'adaptive_heuristic','punts':()},
        {i:i for i in (1,2,3,4)},{i:i for i in (1,2,3,4)},['UT','UT'],['PTS'],
        include_roster=True,opponent_profiles={1:{'policy':'roto'}},
        hero_market_players=beliefs,hero_market={i:100-i for i in (1,2,3,4)})
    # Opponent takes official #1, despite hero perceiving #4 as most urgent.
    assert {p['player_id'] for _,p in seen[0]}=={2,3,4}
    assert result['roster'][0]['player_id']==4
    assert rows[0].get('espn_market_pick') is None
