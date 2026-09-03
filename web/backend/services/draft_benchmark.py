"""Paired policy benchmark for draft strategies.

Selection and evaluation are deliberately separate: a punt may change whom a
policy drafts, but every finished roster is scored under every league category.
"""

from __future__ import annotations

from collections import Counter
from itertools import combinations
import math
import random
from statistics import fmean, pstdev

from core.config import CATEGORIES
from core.projection import can_play_slot
from core.z_score import calculate_z_scores_from_players

from .draft_evaluation import evaluate_projected_rosters

from .draft_simulation import (
    _market_position,
    _market_sigma,
    _next_turn_pick,
    _select_player,
    _slot_at_pick,
    snake_pick_numbers,
)


STRATEGIES = (
    {"id": "roto", "label": "ESPN ROTO", "policy": "roto", "punts": ()},
    {"id": "model_balanced", "label": "Модель без панта", "policy": "model", "punts": ()},
)


def _identity(player):
    return player.get("player_id") or player.get("name")


def _rank_value(player, field):
    value = player.get(field)
    if value is None and field == "espn_roto_rank":
        value = _market_position(player)
    if value is None:
        value = 100_000
    return float(value)


def _feasible_pool(players, roster, picks_left, roster_slots=None):
    from .draft_simulation import unfilled_roster_slots
    missing = list(unfilled_roster_slots(roster, roster_slots))
    if missing and picks_left <= len(missing):
        forced = [player for player in players if any(can_play_slot(player, position) for position in missing)]
        if forced:
            return forced
    return list(players)


def _scenario(players, seed, run):
    market = {}
    opponent_rank = {}
    for player in players:
        identity = _identity(player)
        market_average = _market_position(player) or _rank_value(player, "espn_roto_rank")
        market_rng = random.Random(f"market:{seed}:{run}:{identity}")
        opponent_rng = random.Random(f"opponent:{seed}:{run}:{identity}")
        market[identity] = max(1.0, market_rng.gauss(market_average, _market_sigma(market_average)))
        roto = _rank_value(player, "espn_roto_rank")
        opponent_rank[identity] = max(1.0, opponent_rng.gauss(roto, _market_sigma(roto) * 0.55))
    return market, opponent_rank


def _draft_once(
    players, hero_slot, team_count, rounds, strategy, market, opponent_rank,
    roster_slots=None, categories=None, include_roster=False, opponent_profiles=None,
    evaluation_noise_seed=None,
):
    remaining = {_identity(player): player for player in players}
    rosters = {slot: [] for slot in range(1, team_count + 1)}
    hero_picks = snake_pick_numbers(hero_slot, team_count, rounds)

    for overall in range(1, team_count * rounds + 1):
        if not remaining:
            break
        drafting_slot = _slot_at_pick(overall, team_count)
        if drafting_slot == hero_slot and strategy["policy"] in {"model", "adaptive"}:
            market_order = sorted(
                ([market[identity], player] for identity, player in remaining.items()),
                key=lambda item: item[0],
            )
            pick_index = hero_picks.index(overall)
            selected = _select_player(
                market_order,
                rosters[hero_slot],
                overall,
                rounds - pick_index,
                next_own_pick=_next_turn_pick(hero_picks, pick_index),
                punt_categories=strategy["punts"],
                opponent_rosters=[rosters[slot] for slot in rosters if slot != hero_slot],
                rounds=rounds,
                team_count=team_count,
                roster_slots=roster_slots,
                categories=categories,
                policy_mode="adaptive" if strategy["policy"] == "adaptive" else "legacy",
            )
        elif drafting_slot == hero_slot:
            candidates = _feasible_pool(remaining.values(), rosters[hero_slot], rounds - len(rosters[hero_slot]), roster_slots)
            selected = min(
                candidates,
                key=lambda player: (_rank_value(player, "espn_roto_rank"), market[_identity(player)]),
            )
        else:
            profile = (opponent_profiles or {}).get(drafting_slot)
            if profile and profile.get("policy") in {"model", "adaptive"}:
                slot_picks = [
                    pick for pick in snake_pick_numbers(drafting_slot, team_count, rounds)
                    if pick >= overall
                ]
                market_order = sorted(
                    ([market[identity], player] for identity, player in remaining.items()),
                    key=lambda item: item[0],
                )
                selected = _select_player(
                    market_order,
                    rosters[drafting_slot],
                    overall,
                    len(slot_picks),
                    next_own_pick=_next_turn_pick(slot_picks, 0),
                    punt_categories=tuple(profile.get("punts") or ()),
                    opponent_rosters=[rosters[slot] for slot in rosters if slot != drafting_slot],
                    rounds=rounds,
                    team_count=team_count,
                    roster_slots=roster_slots,
                    categories=categories,
                    policy_mode="adaptive" if profile["policy"] == "adaptive" else "legacy",
                )
            else:
                candidates = _feasible_pool(remaining.values(), rosters[drafting_slot], rounds - len(rosters[drafting_slot]), roster_slots)
                rank_field = "espn_adp" if profile and profile.get("policy") == "adp" else "espn_roto_rank"
                selected = min(
                    candidates,
                    key=lambda player: (
                        _rank_value(player, rank_field),
                        opponent_rank[_identity(player)],
                    ),
                )
        rosters[drafting_slot].append(selected)
        remaining.pop(_identity(selected), None)

    nominal = evaluate_projected_rosters(rosters, hero_slot, categories)
    result = nominal
    if evaluation_noise_seed is not None:
        stressed_rosters = {}
        for team_slot, roster in rosters.items():
            stressed_rosters[team_slot] = []
            for player in roster:
                identity = _identity(player)
                stats = dict(player.get("stats") or {})
                stressed = dict(stats)
                gp = float(stats.get("GP", 65) or 0)
                gp_rng = random.Random(f"projection:{evaluation_noise_seed}:{identity}:GP")
                stressed["GP"] = max(0.0, min(82.0, gp * max(0.55, gp_rng.gauss(1.0, 0.12))))
                for key, value in stats.items():
                    if key in {"GP", "FG%", "FT%", "3PT%", "A/TO"} or not isinstance(value, (int, float)):
                        continue
                    stat_rng = random.Random(f"projection:{evaluation_noise_seed}:{identity}:{key}")
                    stressed[key] = max(0.0, float(value) * max(0.65, stat_rng.gauss(1.0, 0.08)))
                for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "3PA")):
                    if made in stressed and attempted in stressed:
                        stressed[made] = min(stressed[made], stressed[attempted])
                stressed_rosters[team_slot].append({**player, "stats": stressed, "games_played": stressed["GP"]})
        result = evaluate_projected_rosters(stressed_rosters, hero_slot, categories)
        result["nominal_category_wins"] = nominal["category_wins"]
        result["nominal_league_rank"] = nominal["league_rank"]
    if include_roster:
        result["roster"] = list(rosters[hero_slot])
    return result


def _population_profiles(team_count, categories, mode="mixed"):
    """Diverse self-play field: market, old policies, punts, and adaptive agents."""
    from .draft_strategy import strategy_library

    library = strategy_library(categories)
    best_punt = next((row["punt_categories"] for row in library if row["punt_categories"]), ())
    templates = [
        {"policy": "roto", "punts": ()},
        {"policy": "adp", "punts": ()},
        {"policy": "model", "punts": ()},
        {"policy": "model", "punts": best_punt},
    ]
    if mode == "mixed":
        templates.append({"policy": "adaptive", "punts": ()})
    elif mode != "market":
        raise ValueError(f"Unknown opponent population mode: {mode}")
    return {slot: dict(templates[(slot - 1) % len(templates)]) for slot in range(1, team_count + 1)}


def _mean(values):
    return fmean(values) if values else 0.0


def _ci95(values):
    if len(values) < 2:
        mean = _mean(values)
        return [mean, mean]
    mean = _mean(values)
    margin = 1.96 * pstdev(values) / math.sqrt(len(values))
    return [mean - margin, mean + margin]


def _summarize(outcomes, team_count, categories=None):
    categories = list(categories or CATEGORIES)
    category_wins = [row["category_wins"] for row in outcomes]
    return {
        "average_category_wins": round(_mean(category_wins), 3),
        "average_league_rank": round(_mean([row["league_rank"] for row in outcomes]), 3),
        "top_four_rate": round(_mean([row["league_rank"] <= min(4, team_count) for row in outcomes]) * 100, 1),
        "worst_decile_category_wins": round(sorted(category_wins)[max(0, int(len(category_wins) * 0.1) - 1)], 3),
        "category_ranks": {
            category: round(_mean([row["category_ranks"][category] for row in outcomes]), 2)
            for category in categories
        },
    }


def _comparison(candidate_id, baseline_id, outcomes):
    candidate = outcomes[candidate_id]
    baseline = outcomes[baseline_id]
    deltas = [left["category_wins"] - right["category_wins"] for left, right in zip(candidate, baseline)]
    rank_deltas = [right["league_rank"] - left["league_rank"] for left, right in zip(candidate, baseline)]
    interval = _ci95(deltas)
    return {
        "strategy": candidate_id,
        "baseline": baseline_id,
        "delta_category_wins": round(_mean(deltas), 3),
        "delta_category_wins_ci95": [round(value, 3) for value in interval],
        "delta_league_rank": round(_mean(rank_deltas), 3),
        "better_rate": round(_mean([value > 1e-12 for value in deltas]) * 100, 1),
        "tie_rate": round(_mean([abs(value) <= 1e-12 for value in deltas]) * 100, 1),
        "worse_rate": round(_mean([value < -1e-12 for value in deltas]) * 100, 1),
    }


def benchmark_draft_strategies(
    players,
    team_count,
    rounds,
    *,
    punt_category="FG%",
    runs_per_slot=60,
    slots=None,
    seed=260902,
    roster_slots=None,
    categories=None,
):
    categories = list(categories or CATEGORIES)
    usable = [player for player in players if _market_position(player) is not None or player.get("espn_roto_rank") is not None]
    if len(usable) < team_count * rounds:
        rounds = max(1, len(usable) // max(1, team_count))
    strategies = list(STRATEGIES)
    if punt_category in categories:
        strategies.append({
            "id": f"model_punt_{punt_category.lower().replace('%', 'pct')}",
            "label": f"Модель · punt {punt_category}",
            "policy": "model",
            "punts": (punt_category,),
        })
    selected_slots = list(slots or range(1, team_count + 1))
    outcomes = {strategy["id"]: [] for strategy in strategies}
    slot_rows = []

    for slot in selected_slots:
        slot_outcomes = {strategy["id"]: [] for strategy in strategies}
        for run in range(max(1, int(runs_per_slot))):
            market, opponent_rank = _scenario(usable, seed + slot * 1009, run)
            for strategy in strategies:
                result = _draft_once(usable, slot, team_count, rounds, strategy, market, opponent_rank, roster_slots, categories)
                outcomes[strategy["id"]].append(result)
                slot_outcomes[strategy["id"]].append(result)
        slot_rows.append({
            "slot": slot,
            "strategies": {
                strategy["id"]: _summarize(slot_outcomes[strategy["id"]], team_count, categories)
                for strategy in strategies
            },
            "comparisons": [
                _comparison(strategy["id"], "roto", slot_outcomes)
                for strategy in strategies if strategy["id"] != "roto"
            ],
        })

    return {
        "method": "paired_projected_volume_benchmark",
        "evaluator": "Selected ESPN period per-game stats × GP, with per-player previous-season fallback; all league categories",
        "opponents": "stochastic ESPN ROTO followers without punts",
        "categories": categories,
        "roster_slots": list(roster_slots or ()),
        "team_count": team_count,
        "rounds": rounds,
        "runs_per_slot": runs_per_slot,
        "slots": selected_slots,
        "total_paired_scenarios": len(selected_slots) * runs_per_slot,
        "strategies": [
            {
                "id": strategy["id"],
                "label": strategy["label"],
                "punt_categories": list(strategy["punts"]),
                **_summarize(outcomes[strategy["id"]], team_count, categories),
            }
            for strategy in strategies
        ],
        "comparisons": [
            _comparison(strategy["id"], "roto", outcomes)
            for strategy in strategies if strategy["id"] != "roto"
        ],
        "slot_results": slot_rows,
        "limitations": [
            "This is a projection benchmark, not a historical proof of edge.",
            "Opponent deviations from ROTO are synthetic until live draft snapshots are collected.",
            "The evaluator uses projected season volume, not a week-by-week fantasy schedule.",
        ],
    }


def prepare_players_for_categories(players, categories):
    """Recalculate comparable Z profiles for a hypothetical category format."""
    population = [
        {
            "name": player["name"],
            "position": player.get("position", "N/A"),
            "eligible_slots": player.get("eligible_slots") or [],
            "team_id": 0,
            "team_name": "Benchmark",
            "stats": player.get("stats") or {},
        }
        for player in players if player.get("stats")
    ]
    scored = calculate_z_scores_from_players(population, categories=list(categories))["players"]
    by_name = {row["name"]: row["z_scores"] for row in scored}
    return [
        {**player, "z_scores": by_name.get(player["name"], {}), "total_z": sum(by_name.get(player["name"], {}).values())}
        for player in players if player["name"] in by_name
    ]


def benchmark_punt_strategies(
    players,
    team_count,
    rounds,
    categories,
    *,
    max_punts=2,
    roster_slots=None,
    screening_runs=1,
    deep_runs=10,
    finalist_count=10,
    seed=731_021,
):
    """Screen every 0..max_punts combination, then deeply test finalists."""
    categories = tuple(categories)
    prepared = prepare_players_for_categories(players, categories)
    usable = [player for player in prepared if _market_position(player) is not None or player.get("espn_roto_rank") is not None]
    rounds = min(rounds, max(1, len(usable) // max(1, team_count)))
    punt_sets = [()]
    for size in range(1, min(max_punts, len(categories)) + 1):
        punt_sets.extend(combinations(categories, size))
    strategies = [
        {
            "id": "balanced" if not punts else "punt_" + "_".join(category.replace("%", "pct").replace("/", "_").lower() for category in punts),
            "label": "Без панта" if not punts else "Punt " + " + ".join(punts),
            "policy": "model",
            "punts": tuple(punts),
        }
        for punts in punt_sets
    ]
    screening_slots = sorted(set((1, max(1, (team_count + 1) // 2), team_count)))
    screening = {strategy["id"]: [] for strategy in strategies}
    for slot in screening_slots:
        for run in range(max(1, screening_runs)):
            market, opponent_rank = _scenario(usable, seed + slot * 1009, run)
            for strategy in strategies:
                screening[strategy["id"]].append(
                    _draft_once(usable, slot, team_count, rounds, strategy, market, opponent_rank, roster_slots, categories)
                )
    ranked = sorted(
        strategies,
        key=lambda strategy: (
            _mean([row["category_wins"] for row in screening[strategy["id"]]]),
            -_mean([row["league_rank"] for row in screening[strategy["id"]]]),
        ),
        reverse=True,
    )
    balanced = next(strategy for strategy in strategies if strategy["id"] == "balanced")
    finalists = ranked[:max(1, finalist_count)]
    if balanced not in finalists:
        finalists.append(balanced)
    deep = {strategy["id"]: [] for strategy in finalists}
    selection_counts = {strategy["id"]: Counter() for strategy in finalists}
    for slot in range(1, team_count + 1):
        for run in range(max(1, deep_runs)):
            market, opponent_rank = _scenario(usable, seed + 900_000 + slot * 1009, run)
            for strategy in finalists:
                result = _draft_once(
                    usable, slot, team_count, rounds, strategy, market, opponent_rank,
                    roster_slots, categories, include_roster=True,
                )
                deep[strategy["id"]].append(result)
                selection_counts[strategy["id"]].update(
                    player.get("name") for player in result.get("roster", ()) if player.get("name")
                )
    rows = [
        {
            "id": strategy["id"],
            "label": strategy["label"],
            "punt_categories": list(strategy["punts"]),
            "most_selected_players": [
                {"name": name, "draft_frequency": round(count / max(1, team_count * deep_runs) * 100, 1)}
                for name, count in selection_counts[strategy["id"]].most_common(15)
            ],
            **_summarize(deep[strategy["id"]], team_count, categories),
        }
        for strategy in finalists
    ]
    rows.sort(key=lambda row: (row["average_category_wins"], -row["average_league_rank"]), reverse=True)
    return {
        "method": "staged_exhaustive_punt_benchmark",
        "categories": list(categories),
        "max_punts": max_punts,
        "strategies_screened": len(strategies),
        "screening_slots": screening_slots,
        "screening_runs_per_slot": screening_runs,
        "deep_runs_per_slot": deep_runs,
        "deep_scenarios": team_count * deep_runs,
        "finalists": rows,
        "comparisons_to_balanced": [
            _comparison(strategy["id"], "balanced", deep)
            for strategy in finalists if strategy["id"] != "balanced"
        ],
    }


def benchmark_adaptive_vs_legacy(
    players,
    team_count,
    rounds,
    categories,
    *,
    roster_slots=None,
    runs_per_slot=5,
    slots=None,
    seed=1_204_907,
    opponent_field="mixed",
):
    """Paired old/new policy benchmark against a diverse self-play field."""
    from .draft_strategy import strategy_library

    categories = tuple(categories)
    prepared = prepare_players_for_categories(players, categories)
    usable = [
        player for player in prepared
        if _market_position(player) is not None or player.get("espn_roto_rank") is not None
    ]
    rounds = min(rounds, max(1, len(usable) // max(1, team_count)))
    library = strategy_library(categories)
    best_fixed = max(
        (row for row in library if row["punt_categories"]),
        key=lambda row: row["prior_delta"],
        default={"punt_categories": ()},
    )["punt_categories"]
    strategies = (
        {"id": "legacy_balanced", "label": "Прошлая модель · balanced", "policy": "model", "punts": ()},
        {"id": "legacy_best_fixed", "label": "Прошлая модель · лучший фиксированный punt", "policy": "model", "punts": best_fixed},
        {"id": "adaptive_heuristic", "label": "Adaptive projected · без ML", "policy": "adaptive_heuristic", "punts": ()},
        {"id": "adaptive", "label": "Adaptive projected portfolio", "policy": "adaptive", "punts": ()},
    )
    selected_slots = list(slots or range(1, team_count + 1))
    outcomes = {strategy["id"]: [] for strategy in strategies}
    selection_counts = {strategy["id"]: Counter() for strategy in strategies}
    profiles = _population_profiles(team_count, categories, opponent_field)
    for slot in selected_slots:
        for run in range(max(1, int(runs_per_slot))):
            market, opponent_rank = _scenario(usable, seed + slot * 1009, run)
            for strategy in strategies:
                result = _draft_once(
                    usable,
                    slot,
                    team_count,
                    rounds,
                    strategy,
                    market,
                    opponent_rank,
                    roster_slots,
                    categories,
                    include_roster=True,
                    opponent_profiles=profiles,
                    evaluation_noise_seed=f"{seed + slot * 1009}:{run}",
                )
                outcomes[strategy["id"]].append(result)
                selection_counts[strategy["id"]].update(
                    player.get("name") for player in result.get("roster", ()) if player.get("name")
                )

    scenario_count = len(selected_slots) * max(1, int(runs_per_slot))
    return {
        "method": "paired_population_self_play",
        "evaluation": "held-out projection stress: GP stddev 12%, per-game components stddev 8%",
        "categories": list(categories),
        "team_count": team_count,
        "rounds": rounds,
        "slots": selected_slots,
        "runs_per_slot": runs_per_slot,
        "paired_scenarios": scenario_count,
        "opponent_population": [
            "ESPN ROTO", "ESPN ADP", "legacy balanced", "legacy fixed punt",
            *(["adaptive portfolio"] if opponent_field == "mixed" else []),
        ],
        "opponent_field": opponent_field,
        "best_fixed_punt": list(best_fixed),
        "strategies": [
            {
                "id": strategy["id"],
                "label": strategy["label"],
                "punt_categories": list(strategy["punts"]),
                "most_selected_players": [
                    {"name": name, "draft_frequency": round(count / max(1, scenario_count) * 100, 1)}
                    for name, count in selection_counts[strategy["id"]].most_common(12)
                ],
                **_summarize(outcomes[strategy["id"]], team_count, categories),
            }
            for strategy in strategies
        ],
        "comparisons_to_legacy_balanced": [
            _comparison(strategy["id"], "legacy_balanced", outcomes)
            for strategy in strategies if strategy["id"] != "legacy_balanced"
        ],
        "comparisons_to_legacy_fixed": [
            _comparison("adaptive", "legacy_best_fixed", outcomes)
        ],
        "comparisons_to_adaptive_heuristic": [
            _comparison("adaptive", "adaptive_heuristic", outcomes)
        ],
        "limitations": [
            "Self-play is population-based but still synthetic.",
            "Projection and market quality bound the result.",
            "No weekly H2H season simulator is used.",
        ],
    }
