from copy import deepcopy
import numpy as np
from test_draft_v7 import players, teacher, small_config
from scripts import draft_v73_diagnostic as diagnostic
from web.backend.services.draft_ml.v7_data import Arena
from web.backend.services.draft_ml.v7_state import State


def setup_arena():
    config = {**small_config(), 'rounds': 3}
    arena = Arena(config, teacher())
    arena.history = [None, None, None]
    payload = dict(players=players(12), roster_slots=['PG', 'BE', 'BE'])
    settings = {**diagnostic.SETTINGS, 'rounds_sampled': [0, 1, 2],
                'small_candidates': 2, 'large_candidates': 8,
                'small_rollouts': 1, 'large_rollouts': 2, 'audit_rollouts': 2}
    return config, settings, payload, arena


def test_candidates_are_legal_unique_and_cover_baselines():
    config, settings, payload, arena = setup_arena()
    state = State(payload['players'], payload['roster_slots'], 2, 3)
    t, s, expanded = diagnostic.candidates(state, arena, settings)
    assert set(t+s) <= set(expanded) <= set(state.legal())
    assert len(set(expanded)) == len(expanded)
    before = state.pick
    diagnostic.candidates(state, arena, settings)
    assert state.pick == before


def test_selection_uses_expected_utility():
    good = np.array([1.] * 8 + [0., 1., 1.])
    bad = np.array([0.] * 8 + [1., 0., 0.])
    assert diagnostic.choose([0, 1], {0: [bad], 1: [good]}) == 1


def test_episode_reproducible_and_audit_seeds_disjoint(monkeypatch):
    ctx = setup_arena()
    monkeypatch.setattr(diagnostic, 'CTX', ctx)
    arena = ctx[3]
    original = arena.finish
    seeds = []
    def record(*args, **kwargs):
        seeds.append(args[3])
        return original(*args, **kwargs)
    monkeypatch.setattr(arena, 'finish', record)
    first = diagnostic.episode(('strong', 0))
    assert first == diagnostic.episode(('strong', 0))
    assert len(first['states']) == 3
    assert any(':select:' in s for s in seeds)
    assert any(':audit:' in s for s in seeds)
    assert not {s for s in seeds if ':select:' in s} & {s for s in seeds if ':audit:' in s}
    report = diagnostic.summarize([first])
    assert report['decision'] == 'STOP_FOR_USER_REVIEW_NO_TRAINING'
    assert report['arenas']['strong']['local_action_comparisons']['expanded_vs_teacher']['n_drafts'] == 1


def test_arena_assignments_deterministic_and_strong_excludes_weak_anchors():
    arena = setup_arena()[3]
    for name in diagnostic.ARENAS:
        assert diagnostic.assignments_for(arena, name, 'seed') == diagnostic.assignments_for(arena, name, 'seed')
    assignments = diagnostic.assignments_for(arena, 'strong', 'seed')
    assert all(isinstance(v, int) or all(g in arena.teacher for g in v) for v in assignments.values())
