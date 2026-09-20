import numpy as np
import torch

from scripts import draft_v83_distributional as v83
from web.backend.services.draft_ml.v8_state import CATEGORY_VOCAB
from web.backend.services.draft_ml.v83_strategy import DistributionalStrategyScorer, distributional_loss


def test_distributional_model_emits_rank_and_edge_per_profile():
    model = DistributionalStrategyScorer(width=24, heads=4, layers=1, experts=2)
    features = torch.zeros(5, len(CATEGORY_VOCAB), 7)
    masks = torch.zeros(5, len(CATEGORY_VOCAB), dtype=torch.bool); masks[:, :8] = True
    globals_ = torch.zeros(5, 5)
    score, edge = model(features, masks, globals_)
    assert score.shape == edge.shape == (5,)
    assert model.spec["architecture"] == "universal_strategy_distributional_v1"


def test_distributional_loss_accepts_soft_probabilities_and_confirmation_mask():
    model = DistributionalStrategyScorer(width=24, heads=4, layers=1, experts=2)
    count = 5; masks = torch.zeros(count, len(CATEGORY_VOCAB), dtype=torch.bool); masks[:, :8] = True
    row = {
        "features": torch.zeros(count, len(CATEGORY_VOCAB), 7), "masks": masks,
        "globals": torch.zeros(count, 5), "utility_mean": torch.tensor([.5, .6, .55, .4, .45]),
        "utility_std": torch.ones(count) * .05, "best_probability": torch.tensor([.1, .6, .3, 0., 0.]),
        "edge_probability": torch.tensor([.5, .8, .65, .2, .3]),
        "confirmed": torch.tensor([True, True, True, False, False]), "safe_index": torch.tensor(1),
    }
    settings = v83.configuration()[0]["training"]
    loss, metrics = distributional_loss(model, row, settings)
    assert torch.isfinite(loss)
    assert 0 <= metrics["edge_brier"] <= 1


def test_profile_selection_stays_open_until_probability_and_votes_pass():
    profiles = [(), ("FG%",), ("FT%",)]
    scores = np.asarray([[0., 1., .2], [0., 1.1, .1], [0., .9, .3]])
    confidence = {"edge_probability": .65, "minimum_votes": 2, "score_margin": 0.0}
    assert v83.select_profile(scores, np.ones_like(scores) * .6, profiles, confidence)[0] == ()
    assert v83.select_profile(scores, np.ones_like(scores) * .8, profiles, confidence)[0] == ("FG%",)


def test_v83_plan_uses_fresh_projection_and_validated_method():
    plan = v83.plan()
    assert plan["fresh_2027_projections"] is True
    assert plan["formats"] == 17
    assert plan["label_states"] == 323
    assert plan["target_league"]["draft_slot"] == 5
    assert plan["target_format"] == "main-c11-t14-r13"
    assert len(plan["target_league"]["draft_picks"]) == 13
    assert plan["target_league"]["draft_picks"][-1] == 173
    assert plan["auto_promote"] is False


def test_v83_utility_prioritizes_h2h_majority_over_extra_category_volume():
    count = 11
    stable_winner = np.asarray([.60] * count + [.20, 1., 0., .85, 0., .59, .10], dtype=np.float32)
    volatile_volume = np.asarray([.66] * count + [.15, 1., 0., .80, 0., .66, .16], dtype=np.float32)

    assert v83.outcome_utility(stable_winner, count) > v83.outcome_utility(volatile_volume, count)
