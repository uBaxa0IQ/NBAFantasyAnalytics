import random

from scripts import draft_v78_generalization as v78
from web.backend.services.draft_ml.v7_state import State


def players(n=30):
    rows = []
    for i in range(n):
        z = {category: ((i + j * 3) % 11 - 5) / 3 for j, category in enumerate(v78.CATEGORIES)}
        rows.append({'id': i, 'name': str(i), 'eligible_slots': ['PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UTIL'],
                     'z_scores': z, 'stats': {'GP': 70, 'FGM': 5, 'FGA': 10, 'FTM': 3, 'FTA': 4,
                     '3PM': 2, '3PA': 5, 'REB': 5, 'AST': 5, 'STL': 1, 'BLK': 1, 'PTS': 15}})
    return rows


class Arena:
    config = {'team_count': 2}
    def order(self, state, neural=None):
        return [(i, float(-i)) for i in state.legal()]
    def opponent_action(self, state, assignments, seed):
        return self.order(state)[0][0]


def test_train_and_holdout_family_names_are_disjoint():
    assert not set(v78.TRAIN_FAMILIES) & set(v78.VALIDATION_CONDITIONS + v78.HOLDOUT_CONDITIONS)
    assert 'unseen_need' not in v78.TRAIN_FAMILIES
    assert 'unseen_hybrid' not in v78.TRAIN_FAMILIES


def test_all_synthetic_actions_are_legal_and_deterministic():
    state = State(players(), ['UTIL', 'UTIL'], 2, 2)
    arena = Arena()
    policies = [v78.weighted_style('w'), {'kind': 'topk', 'k': 5}, {'kind': 'proxy_need'},
                {'kind': 'sigmoid_need'}, {'kind': 'hybrid'}]
    for policy in policies:
        first = v78.action_for(state, arena, policy, 'fixed')
        second = v78.action_for(state, arena, policy, 'fixed')
        assert first == second
        assert first in state.legal()


def test_weighted_style_is_seeded_and_finite():
    first = v78.weighted_style('seed')
    assert first == v78.weighted_style('seed')
    assert first != v78.weighted_style('different')
    assert set(first['weights']) == set(v78.CATEGORIES)
    assert all(0 <= value < 2 for value in first['weights'].values())
