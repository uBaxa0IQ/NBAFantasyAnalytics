"""Adaptive draft strategy portfolio and projected marginal pick scoring."""

from __future__ import annotations

import math
from statistics import fmean, pstdev

from core.config import REVERSE_CATEGORIES

from .draft_evaluation import projected_team_totals


# Priors come from the held-out deep stage of the exhaustive benchmarks. They
# seed the live search; roster fit and the remaining board update them each pick.
_STANDARD_8 = frozenset(("FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "PTS"))
_CUSTOM_11 = frozenset(("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS"))
_PRECOMPUTED = {
    _STANDARD_8: (
        ((), 0.000),
        (("REB", "BLK"), 0.271),
        (("BLK", "PTS"), 0.249),
        (("FG%", "FT%"), 0.248),
        (("FG%", "BLK"), 0.220),
        (("FG%",), 0.177),
    ),
    _CUSTOM_11: (
        ((), 0.000),
        (("REB", "BLK", "PTS"), 0.456),
        (("REB", "BLK"), 0.392),
        (("FG%", "REB", "PTS"), 0.354),
        (("FG%", "BLK", "PTS"), 0.328),
        (("BLK",), 0.320),
        (("FG%", "FT%", "DD"), 0.295),
        (("3PT%", "REB"), 0.249),
        (("3PT%", "DD"), 0.236),
        (("STL", "BLK"), 0.181),
    ),
}


def strategy_library(categories):
    """Return the benchmark-derived non-dominated strategy library."""
    categories = tuple(categories)
    configured = frozenset(categories)
    entries = _PRECOMPUTED.get(configured)
    if entries is None:
        entries = (((), 0.0),) + tuple(((category,), 0.0) for category in categories)
    return [
        {
            "id": "balanced" if not punts else "punt_" + "_".join(
                category.replace("%", "pct").replace("/", "_").lower()
                for category in punts
            ),
            "punt_categories": tuple(category for category in punts if category in configured),
            "prior_delta": float(prior),
        }
        for punts, prior in entries
    ]


def _softmax(rows, temperature):
    if not rows:
        return []
    ceiling = max(row["strategy_score"] for row in rows)
    weights = [math.exp((row["strategy_score"] - ceiling) / max(0.05, temperature)) for row in rows]
    denominator = sum(weights) or 1.0
    for row, weight in zip(rows, weights):
        row["probability"] = weight / denominator
    return rows


def _projected_adjusted_z(player, category):
    value = float((player.get("z_scores") or {}).get(category, 0.0) or 0.0)
    stats = player.get("stats") or {}
    gp = stats.get("GP", player.get("games_played", 65))
    gp = float(gp) if isinstance(gp, (int, float)) else 65.0
    availability = max(0.0, min(1.15, gp / 65.0))
    if category in {"FG%", "FT%", "3PT%", "A/TO"}:
        availability = math.sqrt(availability)
    return value * availability


def strategy_probabilities(roster, categories, rounds, *, fixed_punts=()):
    """Update punt probabilities from benchmark priors and current roster fit."""
    categories = tuple(categories)
    if fixed_punts:
        punts = tuple(category for category in fixed_punts if category in categories)
        return [{
            "id": "fixed",
            "punt_categories": punts,
            "prior_delta": 0.0,
            "strategy_score": 0.0,
            "probability": 1.0,
        }]

    totals = {
        category: sum(_projected_adjusted_z(player, category) for player in roster or ())
        for category in categories
    }
    roster_size = len(roster or ())
    commitment = min(1.0, roster_size / max(3.0, float(rounds) * 0.45))
    all_mean = fmean(totals.values()) if totals else 0.0
    rows = []
    for strategy in strategy_library(categories):
        punts = strategy["punt_categories"]
        active = [category for category in categories if category not in punts] or list(categories)
        active_values = [totals[category] for category in active]
        active_mean = fmean(active_values) if active_values else 0.0
        relief = active_mean - all_mean
        balance = -pstdev(active_values) * 0.08 if len(active_values) > 1 else 0.0
        early_flexibility = (0.24 if not punts else -0.035 * len(punts)) * (1.0 - commitment)
        strategy_score = (
            strategy["prior_delta"] * (0.72 + commitment * 0.28)
            + relief * commitment * 1.35
            + balance * commitment
            + early_flexibility
        )
        rows.append({**strategy, "strategy_score": strategy_score})

    # Early picks intentionally retain uncertainty; later picks can commit.
    temperature = 0.48 - commitment * 0.25
    rows = _softmax(rows, temperature)
    rows.sort(key=lambda row: row["probability"], reverse=True)
    return rows


def _marginal_vectors(players, roster, categories):
    before = projected_team_totals(roster or (), categories)
    vectors = {}
    for player in players:
        after = projected_team_totals([*(roster or ()), player], categories)
        stats = player.get("stats") or {}
        gp = stats.get("GP", player.get("games_played", 65))
        gp = float(gp) if isinstance(gp, (int, float)) else 65.0
        ratio_reliability = math.sqrt(max(0.0, min(1.15, gp / 65.0)))
        vector = {}
        for category in categories:
            delta = float(after.get(category, 0.0)) - float(before.get(category, 0.0))
            if category in {"FG%", "FT%", "3PT%", "A/TO"}:
                delta *= ratio_reliability
            vector[category] = -delta if category in REVERSE_CATEGORIES else delta
        vectors[id(player)] = vector
    return vectors


def adaptive_rank_window(market_window, context):
    """Rank a feasible market window using a live portfolio of punt policies."""
    if not market_window:
        return [], []
    from .draft_advisor import build_scoring_context, score_draft_pick

    categories = tuple(context.categories)
    players = [player for _, player in market_window]
    strategies = strategy_probabilities(
        context.roster, categories, context.rounds, fixed_punts=context.punt_categories,
    )[:6]
    vectors = _marginal_vectors(players, context.roster, categories)
    category_location = {}
    for category in categories:
        values = [vectors[id(player)][category] for player in players]
        mean = fmean(values)
        scale = pstdev(values) or 1.0
        category_location[category] = (mean, scale)

    strategy_contexts = {}
    strategy_scores = {id(player): [] for player in players}
    legacy_weighted = {id(player): 0.0 for player in players}
    projected_weighted = {id(player): 0.0 for player in players}
    for strategy in strategies:
        punts = strategy["punt_categories"]
        probability = strategy["probability"]
        strategy_context = build_scoring_context(
            roster=context.roster,
            remaining=context.remaining,
            eval_pick=context.eval_pick,
            next_own_pick=context.next_own_pick,
            is_on_the_clock=context.is_on_the_clock,
            picks_until_turn=context.picks_until_turn,
            own_picks_left=context.own_picks_left,
            punt_categories=punts,
            team_count=context.team_count,
            rounds=context.rounds,
            opponent_medians_map=None,
            opponent_rosters=getattr(context, "opponent_rosters", ()),
            roster_slots=context.roster_slots,
            categories=categories,
        )
        strategy_contexts[strategy["id"]] = strategy_context
        active = [category for category in categories if category not in punts] or list(categories)
        for market_pick, player in market_window:
            projected = sum(
                (vectors[id(player)][category] - category_location[category][0])
                / category_location[category][1]
                for category in active
            ) / math.sqrt(max(1, len(active)))
            legacy = score_draft_pick(player, strategy_context, market_pick=market_pick)["score"]
            projected_weighted[id(player)] += probability * projected
            legacy_weighted[id(player)] += probability * legacy
            strategy_scores[id(player)].append(projected)

    def standardized(values):
        mean = fmean(values.values())
        scale = pstdev(values.values()) or 1.0
        return {key: (value - mean) / scale for key, value in values.items()}

    projected_z = standardized(projected_weighted)
    legacy_z = standardized(legacy_weighted)
    ranked = []
    for market_pick, player in market_window:
        robustness = pstdev(strategy_scores[id(player)]) if len(strategy_scores[id(player)]) > 1 else 0.0
        score = projected_z[id(player)] * 0.64 + legacy_z[id(player)] * 0.36 - robustness * 0.08
        ranked.append((score, player, {
            "projected_marginal": projected_z[id(player)],
            "portfolio_legacy": legacy_z[id(player)],
            "strategy_robustness_penalty": robustness * 0.08,
        }))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked, strategies
