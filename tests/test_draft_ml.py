import pytest
from types import SimpleNamespace

from web.backend.services.draft_ml.dataset import dataset_summary, dataset_writer, split_for_scenario
from web.backend.services.draft_ml.cli import _validate_promotion_evidence
from web.backend.services.draft_ml.features import extract_candidate_features
from web.backend.services.draft_ml.inference import maybe_apply_learned_rerank
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


def test_promotion_requires_holdout_and_self_play_to_pass():
    metrics = {
        "value": {"reward": {"mae": 0.2}},
        "policy": {"top1_accuracy": 0.5, "mean_regret": 0.1},
    }
    report = {
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


def test_learned_reranker_is_inert_without_promoted_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAFT_MODEL_CHAMPIONS", str(tmp_path))

    result = maybe_apply_learned_rerank([{}, {}], SimpleNamespace(categories=("PTS",) * 8))

    assert result == {"enabled": False, "reason": "no_promoted_checkpoint"}


def test_promotion_evidence_must_match_checkpoint_and_test_split(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    metrics = {"_provenance": {"checkpoint": str(checkpoint.resolve()), "split": "test"}}
    self_play = {"_provenance": {"checkpoint": str(checkpoint.resolve())}}

    _validate_promotion_evidence(checkpoint, metrics, self_play)
    metrics["_provenance"]["split"] = "validation"

    with pytest.raises(ValueError, match="test split"):
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
