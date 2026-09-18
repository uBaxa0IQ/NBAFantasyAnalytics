from copy import deepcopy
import numpy as np
from scripts import draft_v77_stability as stability
from test_draft_v73_diagnostic import setup_arena


def test_projection_shift_preserves_identity_and_recomputes_finite_z():
    _,_,payload,_=setup_arena()
    players=payload['players']; before=deepcopy(players)
    changed=stability.shifted_players(players,'test')
    assert players==before
    assert changed==stability.shifted_players(players,'test')
    assert [p['player_id'] for p in changed]==[p['player_id'] for p in players]
    for p in changed:
        assert 0<=p['stats']['GP']<=82
        assert p['stats']['3PM']<=p['stats']['FGM']
        assert all(np.isfinite(list(p['z_scores'].values())))


def test_novel_opponents_only_take_legal_actions():
    config,_,payload,arena=setup_arena()
    state=stability.State(payload['players'],payload['roster_slots'],2,3)
    while not state.complete:
        action=stability.rule_action(state,arena,'fixed')
        assert action in state.legal()
        state.apply(action)


def test_report_has_all_replicas_without_winner_selection():
    target=[.5]*8+[.5,1.,0.]
    rows=[dict(condition='strong',results={k:target for k in ('old','v76','repeat1','repeat2')}) for _ in range(2)]
    report=stability.report(rows)
    assert set(report['primary_pooled'])=={'v76','repeat1','repeat2'}
    assert all(x['categories']['delta']==0 for x in report['primary_pooled'].values())
