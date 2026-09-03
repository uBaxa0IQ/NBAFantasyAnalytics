"""Stable numeric feature contract shared by generation and inference."""

from __future__ import annotations

from statistics import fmean

from core.projection import can_play_slot

from ..draft_evaluation import projected_team_totals
from ..draft_simulation import unfilled_roster_slots


RATIO_CATEGORIES = {"FG%", "FT%", "3PT%", "A/TO"}


def _number(value, default=0.0):
    return float(value) if isinstance(value, (int, float)) else float(default)


def _market(player):
    for key in ("espn_market_pick", "espn_adp", "espn_roto_rank"):
        value = player.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 300.0


def _category_strength(roster, category):
    return sum(_number((player.get("z_scores") or {}).get(category)) for player in roster or ())


def extract_candidate_features(
    *, roster, remaining, candidate, opponent_rosters, categories, roster_slots,
    overall_pick, next_own_pick, rounds, team_count, strategy_rows,
):
    """Create a flat, versioned feature mapping for one state/action pair."""
    categories = tuple(categories)
    roster = list(roster or ())
    remaining = list(remaining or ())
    opponents = list(opponent_rosters or ())
    stats = candidate.get("stats") or {}
    before = projected_team_totals(roster, categories)
    after = projected_team_totals([*roster, candidate], categories)
    missing = tuple(unfilled_roster_slots(roster, roster_slots))
    features = {
        "schema_version": 1.0,
        "overall_pick": float(overall_pick),
        "round": float((overall_pick - 1) // max(1, team_count) + 1),
        "roster_size": float(len(roster)),
        "roster_progress": len(roster) / max(1.0, float(rounds)),
        "picks_to_next": float(max(0, (next_own_pick or overall_pick) - overall_pick)),
        "remaining_count": float(len(remaining)),
        "candidate_market": _market(candidate),
        "candidate_market_surplus": _market(candidate) - float(overall_pick),
        "candidate_gp": _number(stats.get("GP", candidate.get("games_played", 0))),
        "candidate_general_z": _number(candidate.get("general_z", candidate.get("total_z", 0))),
        "candidate_position_fit": float(any(can_play_slot(candidate, slot) for slot in missing)) if missing else 1.0,
        "missing_constrained_slots": float(len(missing)),
        "strategy_entropy": 0.0,
        "strategy_count": float(len(strategy_rows or ())),
    }
    probabilities = [_number(row.get("probability")) for row in strategy_rows or ()]
    if probabilities:
        import math
        features["strategy_entropy"] = -sum(p * math.log(max(p, 1e-12)) for p in probabilities)

    for category in categories:
        own_z = _category_strength(roster, category)
        opponent_z = [_category_strength(opponent, category) for opponent in opponents if opponent]
        active_probability = sum(
            _number(row.get("probability"))
            for row in strategy_rows or ()
            if category not in tuple(row.get("punt_categories") or ())
        )
        features[f"own_z::{category}"] = own_z
        features[f"opponent_z::{category}"] = fmean(opponent_z) if opponent_z else 0.0
        features[f"candidate_z::{category}"] = _number((candidate.get("z_scores") or {}).get(category))
        features[f"marginal::{category}"] = _number(after.get(category)) - _number(before.get(category))
        features[f"category_weight::{category}"] = active_probability if strategy_rows else 1.0
        features[f"candidate_stat::{category}"] = _number(stats.get(category))
    return features


def feature_names(records):
    return sorted({name for record in records for name in record.get("features", {})})

