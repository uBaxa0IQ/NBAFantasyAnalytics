from scripts import draft_v75_unknown_search as unknown
from scripts import draft_v73_diagnostic as base
from test_draft_v73_diagnostic import setup_arena


def test_blind_search_uses_prior_not_actual_policy(monkeypatch):
    config,settings,payload,arena=setup_arena()
    settings.update(late_picks=1,terminal_draws=2,cheap_candidates=2,cheap_rollouts=1)
    monkeypatch.setattr(base,'CTX',(config,settings,payload,arena))
    calls=[]
    original=unknown.search
    def observe(*args,**kwargs):
        calls.append(('oracle' if kwargs.get('oracle') is not None else 'blind',kwargs.get('cheap',False)))
        return original(*args,**kwargs)
    monkeypatch.setattr(unknown,'search',observe)
    row=unknown.episode(('strong',0))
    assert calls==[('oracle',False),('blind',False),('blind',True)]
    assert set(row['results'])==set(unknown.MODES)
    assert row['counts']['student_unknown']['search_picks']==1
    assert row['counts']['student_cheap']['continuations']<=2
    again=unknown.episode(('strong',0))
    assert row['results']==again['results']
    report=unknown.report([row,again])
    assert set(report['primary_pooled'])=={'student_unknown_vs_student','student_cheap_vs_student'}


def test_prior_deterministic_without_real_arena_argument():
    arena=setup_arena()[3]
    assert unknown.prior_assignments(arena,'independent-seed',0)==unknown.prior_assignments(arena,'independent-seed',0)
