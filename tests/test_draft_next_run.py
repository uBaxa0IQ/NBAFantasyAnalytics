import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from web.backend.services.draft_ml.cli import _draft_inputs
from web.backend.services.draft_ml.schema import TrainingConfig
from web.backend.services.draft_ml.simulation import (
    DraftEnvironment, _candidate_pool, _strategy_entropy, split_for_episode,
)
from web.backend.services.draft_benchmark import _population_profiles
from scripts.draft_ml_next_run import build_plan, main, ROOT
from scripts.draft_ml_v5_experts import build_plan as build_v5_plan
from scripts.draft_ml_v6_run import build_plan as build_v6_plan
from scripts.draft_ml_v6_2_run import build_plan as build_v62_plan
from scripts.draft_ml_v6_3_run import build_plan as build_v63_plan


def test_transient_http_retries_but_permanent_errors_do_not(monkeypatch):
    from web.backend import dependencies
    monkeypatch.setattr('web.backend.services.draft_ml.cli.time.sleep', lambda _: None)
    transient = Mock(side_effect=HTTPException(status_code=503))
    monkeypatch.setattr(dependencies, 'get_league_meta', transient)
    with pytest.raises(RuntimeError, match='after 4 attempts'):
        _draft_inputs(SimpleNamespace(input_snapshot=None, team_id=7), TrainingConfig())
    assert transient.call_count == 4
    permanent = Mock(side_effect=HTTPException(status_code=401))
    monkeypatch.setattr(dependencies, 'get_league_meta', permanent)
    with pytest.raises(HTTPException):
        _draft_inputs(SimpleNamespace(input_snapshot=None, team_id=7), TrainingConfig())
    assert permanent.call_count == 1


def test_balanced_candidates_include_value_alternatives():
    players = [{"player_id": i, "name": str(i), "general_z": i, "espn_market_pick": i} for i in range(1,9)]
    env = DraftEnvironment(players, ['PTS'], ['UT']*13, TrainingConfig(candidate_pool='balanced'), 0)
    env.market = {i:i for i in range(1,9)}
    selected = _candidate_pool(env,4)
    assert [p['player_id'] for p in selected] == [1,8,2,7]


def test_behavior_choice_is_never_dropped_from_candidate_pool():
    players = [{"player_id": i, "name": str(i), "general_z": i, "espn_market_pick": i} for i in range(1, 9)]
    env = DraftEnvironment(players, ['PTS'], ['UT'] * 13, TrainingConfig(candidate_pool='balanced'), 0)
    env.market = {i: i for i in range(1, 9)}

    selected = _candidate_pool(env, 4, required=(players[4],))

    assert len(selected) == 4
    assert selected[0]['player_id'] == 5


def test_flexibility_is_measured_after_the_candidate_pick(monkeypatch):
    def probabilities(roster, categories, rounds):
        probability = 0.5 if roster[-1]['name'] == 'flexible' else 0.99
        return [{"probability": probability}, {"probability": 1 - probability}]
    monkeypatch.setattr(
        'web.backend.services.draft_ml.simulation.strategy_probabilities', probabilities,
    )

    flexible = _strategy_entropy([], {'name': 'flexible'}, ('PTS',), 13)
    committed = _strategy_entropy([], {'name': 'committed'}, ('PTS',), 13)

    assert flexible > committed


def test_each_market_field_combination_has_all_hero_slots(monkeypatch):
    monkeypatch.setattr('web.backend.services.draft_ml.simulation.prepare_benchmark_market',lambda p,c,m:p)
    config = TrainingConfig(episodes=480,market_models=('conservative','espn_draft','league_rater','category_z'),
                            opponent_fields=('human','heuristic_mixed'),experiment_id='v4')
    counts = Counter()
    for index in range(config.episodes):
        env = DraftEnvironment([],['PTS'],['UT'],config,index)
        counts[(env.market_model,env.opponent_field,env.hero_slot)] += 1
    assert len(counts) == 80
    assert set(counts.values()) == {6}


def test_v4_split_is_exactly_stratified_by_market_and_field():
    config = TrainingConfig(
        episodes=480,
        market_models=('conservative', 'espn_draft', 'league_rater', 'category_z'),
        opponent_fields=('human', 'heuristic_mixed'),
        experiment_id='v4',
    )
    counts = Counter()
    for episode in range(config.episodes):
        group = episode // config.team_count
        cell = (
            config.market_models[group % len(config.market_models)],
            config.opponent_fields[(group // len(config.market_models)) % len(config.opponent_fields)],
        )
        counts[(*cell, split_for_episode(config, episode))] += 1

    assert set(counts.values()) == {6, 48}
    for market in config.market_models:
        for field in config.opponent_fields:
            assert counts[(market, field, 'train')] == 48
            assert counts[(market, field, 'validation')] == 6
            assert counts[(market, field, 'test')] == 6


def test_new_counterfactual_branches_do_not_mutate_the_parent():
    env=DraftEnvironment([{'player_id':1,'name':'A','stats':{'PTS':1}}],['PTS'],['UT'],TrainingConfig(experiment_id='v4'),0)
    branch=env.clone()
    branch.remaining[1]['stats']['PTS']=999
    assert env.remaining[1]['stats']['PTS']==1


def test_fixed_opponents_do_not_load_the_candidate_model():
    assert {p['policy'] for p in _population_profiles(10,['PTS'],'human').values()} == {'roto','adp'}
    policies = {p['policy'] for p in _population_profiles(10,['PTS'],'heuristic_mixed').values()}
    assert 'adaptive' not in policies
    assert 'adaptive_heuristic' in policies


def test_invalid_new_settings_rejected():
    for kwargs in [dict(market_models=()),dict(opponent_fields=('oops',)),dict(candidate_pool='oops')]:
        with pytest.raises(ValueError):
            TrainingConfig(**kwargs).validate()


def test_runner_defaults_to_plan_without_launch(monkeypatch,capsys):
    monkeypatch.setattr('scripts.draft_ml_next_run.build_plan',lambda *a:{'status':'prepared_not_started'})
    monkeypatch.setattr('scripts.draft_ml_next_run.execute',lambda *a:pytest.fail('must not execute'))
    assert main([])==0
    assert json.loads(capsys.readouterr().out)['status']=='prepared_not_started'


def test_v5_reuses_dataset_and_precommits_safe_routes():
    plan = build_v5_plan()

    assert len(plan['stages']) == 16
    assert not any(stage['name'] == 'generate' for stage in plan['stages'])
    assert plan['safe_ml_markets'] == ['espn_draft', 'category_z']
    assert plan['fallback_markets'] == ['conservative', 'league_rater']
    assert plan['constraints']['auto_promote'] is False


def test_v6_plan_has_market_free_training_and_external_benchmarks_only():
    plan = build_v6_plan()

    assert plan['training_full_drafts_max'] == 21456
    assert plan['training_full_drafts_min_with_early_stop'] == 12816
    assert plan['stages'][0]['name'] == 'evolve'
    assert len(plan['stages']) == 9
    assert plan['guarantees']['market_features_in_training'] is False
    assert plan['guarantees']['adp_in_training'] is False
    assert plan['guarantees']['player_rater_in_training'] is False
    assert plan['guarantees']['auto_promote'] is False
    assert plan['guarantees']['early_stopping'] is True
    assert plan['guarantees']['fixed_validation_arena'] is True
    assert plan['guarantees']['all_generation_champions_considered'] is True


def test_v62_plan_precommits_five_seeds_diagnostics_and_frozen_ensemble():
    plan = build_v62_plan()

    assert plan['training_full_drafts_max_total'] == 90400
    assert plan['diagnostic_full_drafts'] == 10000
    assert plan['final_ensemble_benchmark_full_drafts'] == 4000
    assert len(plan['training_seeds']) == 5
    assert len(plan['stages']) == 54
    assert all(stage['kind'] == 'evolve' for stage in plan['stages'][:5])
    assert plan['guarantees']['multi_objective_fitness'] is True
    assert plan['guarantees']['niche_elites'] is True
    assert plan['guarantees']['diagnostics_do_not_select_members'] is True
    assert plan['guarantees']['final_benchmark_seed_separate'] is True


def test_v63_plan_freezes_meta_selection_before_new_holdout():
    plan = build_v63_plan()

    assert plan['candidate_pool'] == 40
    assert plan['meta_validation_full_drafts'] == 3200
    assert plan['crossplay_full_drafts'] == 1600
    assert plan['holdout_full_drafts'] == 8000
    assert len(plan['stages']) == 19
    assert plan['stages'][2]['name'] == 'build-weighted-ensemble'
    assert plan['guarantees']['ensemble_frozen_before_holdout'] is True
    assert plan['guarantees']['final_holdout_seed_unused'] is True
    assert plan['guarantees']['v62_control_same_holdout'] is True
