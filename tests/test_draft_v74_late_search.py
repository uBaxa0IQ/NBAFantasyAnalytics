from scripts import draft_v74_late_search as late
from scripts import draft_v73_diagnostic as base
from test_draft_v73_diagnostic import setup_arena


def test_full_draft_late_search_counts_and_separate_terminal_draws(monkeypatch):
    config, settings, payload, arena = setup_arena()
    settings.update(late_picks=2, terminal_draws=2)
    monkeypatch.setattr(base, 'CTX', (config, settings, payload, arena))
    row = late.episode(('strong', 0))
    assert set(row['results']) == set(late.MODES)
    for mode in late.MODES:
        assert len(row['results'][mode]) == 11
        assert row['counts'][mode]['search_picks'] == (2 if mode.endswith('_late') else 0)
        assert row['timings'][mode]['total_seconds'] >= 0
    again = late.episode(('strong', 0))
    assert row['results'] == again['results']
    assert row['counts'] == again['counts']
    report = late.report([row, again])
    assert report['decision'] == 'STOP_FOR_USER_REVIEW_NO_TRAINING'
    assert report['primary_pooled']['teacher_late_vs_teacher']['categories']['n_drafts'] == 2


def test_selection_and_terminal_seed_namespaces(monkeypatch):
    config, settings, payload, arena = setup_arena()
    settings.update(late_picks=1, terminal_draws=2)
    monkeypatch.setattr(base, 'CTX', (config, settings, payload, arena))
    original = late.State.targets
    seeds = []
    def record(self, hero, seed, *args):
        seeds.append(seed)
        return original(self, hero, seed, *args)
    monkeypatch.setattr(late.State, 'targets', record)
    late.episode(('mixed', 1))
    assert any(':selection:' in s for s in seeds)
    assert any(':terminal-audit:' in s for s in seeds)
    assert all(s.startswith('v74:') for s in seeds)
    assert not {s for s in seeds if ':selection:' in s} & {s for s in seeds if ':terminal-audit:' in s}
