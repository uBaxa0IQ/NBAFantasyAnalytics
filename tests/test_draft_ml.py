import hashlib
import json

import pytest
from types import SimpleNamespace

from web.backend.services.draft_ml.dataset import dataset_summary, dataset_writer, split_for_scenario
from web.backend.services.draft_ml.cli import _validate_promotion_evidence
from web.backend.services.draft_ml.features import extract_candidate_features
from web.backend.services.draft_ml.evolution import (
    EvolutionConfig, evolve_population, initial_population, market_free_feature_rows,
    rank_market_free_ensemble_candidates,
)
from web.backend.services.draft_ml.inference import maybe_apply_learned_rerank
from web.backend.services.draft_ml.model import (
    DraftModelBundle, _tune_rerank_weight, train_market_expert, train_models,
)
from web.backend.services.draft_ml.promotion import promotion_decision
from web.backend.services.draft_ml.schema import TrainingConfig, categories_for_format
from web.backend.services.draft_ml.simulation import generate_dataset


def test_training_config_is_explicit_and_validated():
    config = TrainingConfig(episodes=10, candidate_count=6, rollouts_per_candidate=2)

    assert config.validate() is config
    assert categories_for_format("standard8")[-1] == "PTS"
    with pytest.raises(ValueError):
        TrainingConfig(episodes=0).validate()
    with pytest.raises(ValueError):
        TrainingConfig(format_name="unknown").validate()


def test_dataset_split_keeps_whole_scenario_together(tmp_path):
    path = tmp_path / "sample.jsonl.gz"
    with dataset_writer(path) as write:
        write({"scenario_id": "same", "state_id": "a", "features": {}, "labels": {}})
        write({"scenario_id": "same", "state_id": "b", "features": {}, "labels": {}})

    summary = dataset_summary(path)

    assert summary[split_for_scenario("same")] == 2
    assert summary["states"] == 2


def test_feature_contract_contains_projected_marginals_and_strategy_weights():
    candidate = {
        "name": "Candidate", "position": "PG", "eligible_slots": ["PG", "G", "UT"],
        "espn_market_pick": 12, "games_played": 78,
        "stats": {"GP": 78, "PTS": 20, "AST": 7},
        "z_scores": {"PTS": 1.2, "AST": 1.0},
    }
    features = extract_candidate_features(
        roster=[], remaining=[candidate], candidate=candidate, opponent_rosters=[],
        categories=("PTS", "AST"), roster_slots=("PG", "UT"), overall_pick=10,
        next_own_pick=31, rounds=2, team_count=10,
        strategy_rows=[{"probability": 0.75, "punt_categories": ()}, {"probability": 0.25, "punt_categories": ("AST",)}],
    )

    assert features["marginal::PTS"] == 1560
    assert features["category_weight::PTS"] == 1.0
    assert features["category_weight::AST"] == 0.75
    assert features["schema_version"] == 2.0
    assert features["market_source::unknown"] == 1.0


def test_feature_contract_identifies_league_specific_market():
    candidate = {
        "name": "Candidate", "position": "PG", "eligible_slots": ["PG", "UT"],
        "espn_market_pick": 12, "market_rank_source": "espn_league_rater_default",
        "market_category_match": True, "stats": {"GP": 75, "PTS": 20},
        "z_scores": {"PTS": 1.0},
    }
    features = extract_candidate_features(
        roster=[], remaining=[candidate], candidate=candidate, opponent_rosters=[],
        categories=("PTS",), roster_slots=("PG", "UT"), overall_pick=10,
        next_own_pick=31, rounds=2, team_count=10, strategy_rows=[],
    )

    assert features["market_source::league_rater"] == 1.0
    assert features["market_category_match"] == 1.0


def test_reranker_weight_is_selected_from_validation_regret():
    np = pytest.importorskip("numpy")
    records = [
        {"state_id": "one", "labels": {"reward": 2.0}},
        {"state_id": "one", "labels": {"reward": 1.0}},
        {"state_id": "two", "labels": {"reward": 4.0}},
        {"state_id": "two", "labels": {"reward": 0.0}},
    ]
    reward_predictions = np.asarray([2.0, 1.0, 4.0, 0.0])
    wrong_policy = np.asarray([0.1, 0.9, 0.1, 0.9])

    weight, trials = _tune_rerank_weight(records, reward_predictions, wrong_policy, np)

    assert weight == 0.4
    assert next(row for row in trials if row["reward_weight"] == weight)["mean_regret"] == 0.0
    assert len(trials) == 6


def test_promotion_requires_holdout_and_self_play_to_pass():
    metrics = {
        "value": {"reward": {"mae": 0.2}},
        "policy": {"top1_accuracy": 0.5, "mean_regret": 0.1},
    }
    report = {
        "benchmark_version": 2,
        "comparisons_to_adaptive_heuristic": [{"delta_category_wins_ci95": [0.1, 0.4]}],
        "strategies": [
            {"id": "legacy_balanced", "worst_decile_category_wins": 4.0},
            {"id": "adaptive", "worst_decile_category_wins": 4.2},
        ],
        "comparisons_to_legacy_balanced": [
            {"strategy": "adaptive", "delta_category_wins_ci95": [0.1, 0.4]},
        ],
    }

    accepted = promotion_decision(metrics, report)
    report["comparisons_to_legacy_balanced"][0]["delta_category_wins_ci95"] = [-0.1, 0.4]
    rejected = promotion_decision(metrics, report)

    assert accepted["approved"] is True
    assert rejected["approved"] is False


def test_promotion_gates_the_live_blended_reranker():
    metrics = {
        "value": {"reward": {"mae": 0.2}},
        "policy": {"top1_accuracy": 0.9, "mean_regret": 0.01},
        "reranker": {"top1_accuracy": 0.1, "mean_regret": 0.5},
    }
    report = {
        "benchmark_version": 2,
        "comparisons_to_adaptive_heuristic": [{"delta_category_wins_ci95": [0.1, 0.2]}],
        "strategies": [
            {"id": "legacy_balanced", "worst_decile_category_wins": 4.0},
            {"id": "adaptive", "worst_decile_category_wins": 4.1},
        ],
        "comparisons_to_legacy_balanced": [
            {"strategy": "adaptive", "delta_category_wins_ci95": [0.1, 0.2]},
        ],
    }

    decision = promotion_decision(metrics, report)

    assert decision["checks"]["policy_top1"] is False
    assert decision["checks"]["policy_regret"] is False


def test_learned_reranker_is_inert_without_promoted_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAFT_MODEL_CHAMPIONS", str(tmp_path))
    monkeypatch.setenv("DRAFT_DISABLE_V8", "1")

    result = maybe_apply_learned_rerank([{}, {}], SimpleNamespace(categories=("PTS",) * 8))

    assert result == {"enabled": False, "reason": "no_promoted_checkpoint"}


def test_promotion_evidence_must_match_checkpoint_and_test_split(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text('{"metadata": {}}', encoding="utf-8")
    metrics = {"_provenance": {"checkpoint": str(checkpoint.resolve()), "split": "test"}}
    self_play = {"benchmark_version": 2, "_provenance": {"checkpoint": str(checkpoint.resolve())}}

    _validate_promotion_evidence(checkpoint, metrics, self_play)
    metrics["_provenance"]["split"] = "validation"

    with pytest.raises(ValueError, match="test split"):
        _validate_promotion_evidence(checkpoint, metrics, self_play)


def test_previous_season_only_checkpoint_cannot_be_promoted(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text(
        '{"metadata": {"projection_fallback_only": true}}', encoding="utf-8",
    )
    provenance = {"checkpoint": str(checkpoint.resolve())}
    metrics = {"_provenance": {**provenance, "split": "test"}}
    self_play = {"benchmark_version": 2, "_provenance": provenance}

    with pytest.raises(ValueError, match="promotion is forbidden"):
        _validate_promotion_evidence(checkpoint, metrics, self_play)


def test_dataset_generation_refuses_to_overwrite_existing_version(tmp_path):
    output = tmp_path / "dataset.jsonl.gz"
    output.write_bytes(b"already here")

    with pytest.raises(FileExistsError, match="already exists"):
        generate_dataset([], ("PTS",), (), TrainingConfig(episodes=1), output)


def test_resumed_generation_requires_complete_seed_episodes(tmp_path):
    seed = tmp_path / "seed.jsonl.gz"
    with dataset_writer(seed) as write:
        write({"scenario_id": "standard8:0", "state_id": "only-one", "features": {}, "labels": {}})

    with pytest.raises(ValueError, match="incomplete"):
        generate_dataset(
            [], ("PTS",), (),
            TrainingConfig(episodes=2, rounds=1, candidate_count=2),
            tmp_path / "resumed.jsonl.gz",
            start_episode=1,
            seed_dataset=seed,
        )


def test_auto_resume_keeps_committed_episodes_and_skips_them(tmp_path, monkeypatch):
    from web.backend.services.draft_ml import simulation
    def rows(episode):
        return [{"scenario_id": f"standard8:{episode}", "state_id": f"s{episode}",
                 "candidate_id": index, "features": {},
                 "labels": {"is_best": int(index == 0), "selected_by_behavior": int(index == 0)}}
                for index in range(2)]
    seed = tmp_path / "seed.jsonl.gz"
    with dataset_writer(seed) as write:
        for record in rows(0) + rows(1)[:1]:
            write(record)
    calls = []
    def episode_generator(players, categories, slots, config, index):
        calls.append(index)
        return rows(index)
    monkeypatch.setattr(simulation, "generate_episode", episode_generator)
    config = TrainingConfig(episodes=3, candidate_count=2, rounds=1, workers=1)
    output = tmp_path / "out.jsonl.gz"
    result = generate_dataset([], ("PTS",), (), config, output, seed_dataset=seed, auto_resume=True)
    assert calls == [1, 2]
    assert result["legacy_resume_unverified"] is True
    assert dataset_summary(output)["total"] == 6
    assert len(list((tmp_path / "out.jsonl.gz.episodes").glob("episode-*.json"))) == 3
    generate_dataset([], ("PTS",), (), config, output, auto_resume=True)
    assert calls == [1, 2]


def test_completed_resume_rejects_changed_config(tmp_path, monkeypatch):
    from web.backend.services.draft_ml import simulation
    def episode_generator(players, categories, slots, config, index):
        return [{"scenario_id": f"standard8:{index}", "state_id": f"s{index}",
                 "candidate_id": candidate, "features": {},
                 "labels": {"is_best": int(candidate == 0),
                            "selected_by_behavior": int(candidate == 0)}}
                for candidate in range(2)]
    monkeypatch.setattr(simulation, "generate_episode", episode_generator)
    output = tmp_path / "out.jsonl.gz"
    config = TrainingConfig(episodes=2, candidate_count=2, rounds=1, workers=1)
    generate_dataset([], ("PTS",), (), config, output)

    with pytest.raises(ValueError, match="does not match"):
        generate_dataset(
            [], ("PTS",), (),
            TrainingConfig(episodes=2, candidate_count=3, rounds=1, workers=1),
            output, auto_resume=True,
        )


def test_market_expert_checkpoint_is_isolated_and_auditable(tmp_path):
    pytest.importorskip("sklearn")
    dataset = tmp_path / "tiny.jsonl.gz"
    with dataset_writer(dataset) as write:
        for split, state in (("train", "t"), ("validation", "v"), ("test", "x")):
            for candidate, reward in (("best", 2.0), ("other", 1.0)):
                write({
                    "scenario_id": state, "state_id": state, "split": split,
                    "market_model": "conservative", "candidate_id": candidate,
                    "features": {"signal": reward},
                    "labels": {
                        "expected_category_wins": reward,
                        "expected_league_rank": 3.0 - reward,
                        "downside": 0.0, "reward": reward,
                        "is_best": int(candidate == "best"),
                    },
                })
    base = tmp_path / "base"
    expert = tmp_path / "expert"
    train_models(dataset, base, random_seed=1, metadata={"format": "standard8"})

    manifest = train_market_expert(
        dataset, base, expert, "conservative", random_seed=2,
        metadata={"research_only": True},
    )

    assert manifest["expert_market"] == "conservative"
    assert manifest["rerank_reward_weight"] == 0.0
    assert manifest["metadata"]["research_only"] is True
    assert set(manifest["artifact_sha256"]) == {
        "vectorizer.joblib", "policy.joblib", "value_expected_category_wins.joblib",
        "value_expected_league_rank.joblib", "value_downside.joblib", "value_reward.joblib",
    }


def test_market_free_policy_features_ignore_adp_and_player_rater():
    base = {
        "player_id": 1, "name": "Same", "position": "PG", "eligible_slots": ["PG", "UT"],
        "general_z": 1.0, "z_scores": {"PTS": 1.2}, "stats": {"GP": 75, "PTS": 20},
    }
    first = {**base, "espn_adp": 5, "espn_roto_rank": 7, "espn_league_rater_rank": 2}
    second = {**base, "espn_adp": 250, "espn_roto_rank": 280, "espn_league_rater_rank": 299}
    common = dict(
        roster=[], remaining=[first, second], opponent_rosters=[], categories=("PTS",),
        roster_slots=("PG", "UT"), overall_pick=1, next_own_pick=20,
        rounds=2, team_count=10,
    )

    rows = market_free_feature_rows([first, second], **common)

    assert rows[0] == rows[1]
    assert all("market" not in name and "adp" not in name and "rater" not in name for name in rows[0])


def test_tiny_population_evolution_writes_resumable_market_free_checkpoint(tmp_path, monkeypatch):
    categories = ("PTS", "AST")
    players = [
        {
            "player_id": index, "name": f"P{index}", "position": "PG",
            "eligible_slots": ["PG", "UT"], "general_z": float(20 - index) / 10,
            "z_scores": {"PTS": float(index % 5), "AST": float((index * 2) % 5)},
            "stats": {"GP": 70, "PTS": 10 + index, "AST": 2 + index % 5},
            "stats_source": "previous_season",
        }
        for index in range(1, 13)
    ]
    config = EvolutionConfig(
        population_size=4, generations=1, drafts_per_generation=2, final_drafts=2,
        team_count=4, rounds=2, elite_count=1, parent_pool=2,
        hall_slots_per_draft=1, hall_max_size=4,
        anchor_slots_per_draft=1, anchor_pool_size=4,
        validation_drafts=2, finalist_count=2, workers=1,
        candidate_limit=6, seed=7,
    )

    manifest = evolve_population(players, categories, ("PG", "UT"), config, tmp_path)
    resumed = evolve_population(players, categories, ("PG", "UT"), config, tmp_path)

    assert manifest == resumed
    assert manifest["policy_type"] == "market_free_linear_v1"
    assert manifest["uses_market_features"] is False
    assert manifest["selection_scope"] == "all_generation_champions_via_fixed_validation_arena"
    assert manifest["generation_champions_considered"] == 1
    assert manifest["metadata"]["projection_fallback_only"] is True
    assert (tmp_path / "evolution-state.json").is_file()
    assert DraftModelBundle(tmp_path / "checkpoint").market_free_genome["weights"]
    monkeypatch.setenv("DRAFT_MODEL_CHECKPOINT", str(tmp_path / "checkpoint"))
    context = SimpleNamespace(
        roster=[], remaining=players, opponent_rosters=[], categories=categories,
        roster_slots=("PG", "UT"), eval_pick=1, next_own_pick=8,
        rounds=2, team_count=4, punt_categories=(),
    )
    candidates = [dict(player) for player in players]

    result = maybe_apply_learned_rerank(candidates, context)

    assert result["enabled"] is True
    assert result["policy_type"] == "market_free_linear_v1"
    assert result["uses_market_features"] is False


def test_market_free_ensemble_averages_member_ranks():
    categories = ("PTS", "AST")
    candidates = [
        {
            "player_id": index, "name": f"P{index}", "position": "PG",
            "eligible_slots": ["PG", "UT"], "general_z": 0.0,
            "z_scores": {"PTS": pts, "AST": ast}, "stats": {"GP": 75},
        }
        for index, (pts, ast) in enumerate(((3, 0), (2, 2), (0, 3)), 1)
    ]
    names = market_free_feature_rows(
        candidates, roster=[], remaining=candidates, opponent_rosters=[],
        categories=categories, roster_slots=("PG", "UT"), overall_pick=1,
        next_own_pick=8, rounds=2, team_count=4,
    )[0].keys()
    pts_weights = dict.fromkeys(names, 0.0)
    ast_weights = dict.fromkeys(names, 0.0)
    balanced_weights = dict.fromkeys(names, 0.0)
    pts_weights["z::PTS"] = 1.0
    ast_weights["z::AST"] = 1.0
    balanced_weights["z::PTS"] = 1.0
    balanced_weights["z::AST"] = 1.0
    context = SimpleNamespace(
        roster=[], remaining=candidates, opponent_rosters=[], categories=categories,
        roster_slots=("PG", "UT"), eval_pick=1, next_own_pick=8,
        rounds=2, team_count=4,
    )

    ranked = rank_market_free_ensemble_candidates(
        candidates, context,
        [{"weights": pts_weights}, {"weights": ast_weights}, {"weights": balanced_weights}],
    )

    assert ranked[0][0]["name"] == "P2"

    weighted = rank_market_free_ensemble_candidates(
        candidates, context,
        [
            {"weights": pts_weights, "ensemble_weight": 10.0},
            {"weights": ast_weights, "ensemble_weight": 1.0},
            {"weights": balanced_weights, "ensemble_weight": 1.0},
        ],
    )

    assert weighted[0][0]["name"] == "P1"


def test_model_bundle_loads_market_free_ensemble(tmp_path):
    genomes = [{"id": "a", "weights": {"general_z": 1.0}}, {"id": "b", "weights": {"gp": 1.0}}]
    artifact = tmp_path / "genomes.json"
    artifact.write_text(json.dumps(genomes), encoding="utf-8")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "policy_type": "market_free_ensemble_v1",
        "artifact_sha256": {"genomes.json": digest},
    }), encoding="utf-8")

    bundle = DraftModelBundle(tmp_path)

    assert bundle.market_free_genome is None
    assert bundle.market_free_genomes == genomes
