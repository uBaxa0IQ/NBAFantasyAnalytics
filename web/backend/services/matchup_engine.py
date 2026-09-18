"""ESPN adapter for the pure probabilistic core."""

from __future__ import annotations

from time import monotonic
from collections import defaultdict
from statistics import stdev
from math import isfinite
from typing import Any, Mapping, Sequence

from core.config import MATCHUP_MC_TRIALS, PERIODS
from core.matchup_mc import ENGINE_VERSION, simulate_matchup_odds, stable_seed
from core.player_rates import attach_player_rates
from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    has_game,
    optimize_daily_lineup,
    player_value,
)
from core.snapshot import build_league_snapshot
from .forecast_history import calibration_temperature


def _identity(row: Mapping[str, Any]) -> Any:
    return row.get("player_id") or row.get("name")


def _period_index(league_metadata, period: str) -> dict[Any, dict[str, Any]]:
    return {
        _identity(row): row.get("stats") or {}
        for row in league_metadata.get_all_players_stats(period, "avg")
    }


def _historical_std_index(league_metadata) -> dict[Any, dict[str, float]]:
    """Estimate per-game spread from recent completed matchup boxes when GP exists."""
    cache = getattr(league_metadata, "_player_std_cache", None)
    if cache and monotonic() - cache[0] < 300:
        return cache[1]
    current = int(league_metadata.league.currentMatchupPeriod)
    samples = defaultdict(lambda: defaultdict(list))
    for week in range(max(1, current - 6), current):
        for team in league_metadata.get_all_teams_stats_for_week(week).values():
            for player in team.get("players", []):
                stats = player.get("stats") or {}
                games = stats.get("GP")
                if not isinstance(games, (int, float)) or not isfinite(float(games)) or games <= 0:
                    continue
                identity = player.get("player_id") or player.get("name")
                for key, value in stats.items():
                    if isinstance(value, (int, float)) and key != "GP":
                        per_game = float(value) / float(games)
                        if isfinite(per_game):
                            samples[identity][key].append(per_game)
    result = {
        identity: {key: stdev(values) for key, values in categories.items() if len(values) >= 3}
        for identity, categories in samples.items()
    }
    league_metadata._player_std_cache = (monotonic(), result)
    return result


def build_engine_inputs(league_metadata, period: str) -> dict[str, Any]:
    snapshot = build_league_snapshot(league_metadata, period)
    period_rows = {
        "season": _period_index(league_metadata, PERIODS["total"]),
        "recent": _period_index(league_metadata, PERIODS["last_15"]),
        "projected": _period_index(league_metadata, PERIODS["projected"]),
        "std": _historical_std_index(league_metadata),
    }
    players_by_team = {}
    for team in league_metadata.get_teams():
        players = [player.as_projection_player() for player in snapshot.team_players(team.team_id)]
        players_by_team[team.team_id] = attach_player_rates(players, period_rows)
    return {
        "snapshot": snapshot,
        "players_by_team": players_by_team,
        "teams": {team.team_id: team for team in league_metadata.get_teams()},
        "categories": tuple(league_metadata.get_categories()),
        "reverse_categories": tuple(league_metadata.reverse_categories),
        "calibration": calibration_temperature(league_metadata.league_id, league_metadata.year),
    }


def find_opponent(league_metadata, team_id: int, matchup_period: int) -> int | None:
    box = league_metadata.get_matchup_box_score(matchup_period, team_id)
    if box:
        return int(box["opponent_id"])
    for matchup in league_metadata.get_schedule_matchups(matchup_period, matchup_period):
        if matchup["team1_id"] == team_id:
            return int(matchup["team2_id"])
        if matchup["team2_id"] == team_id:
            return int(matchup["team1_id"])
    return None


def simulate_pair(
    league_metadata,
    inputs: dict[str, Any],
    team1_id: int,
    team2_id: int,
    matchup_period: int,
    *,
    remaining_only: bool = False,
    trials: int = MATCHUP_MC_TRIALS,
    seed: int | None = None,
    availability_overrides1: Mapping[Any, float] | None = None,
    availability_overrides2: Mapping[Any, float] | None = None,
    roster_overrides: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    forced_lineups1: Mapping[int, Sequence[Any]] | None = None,
    forced_lineups2: Mapping[int, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    league = league_metadata.league
    current_period = int(league.currentMatchupPeriod)
    use_remaining = remaining_only and matchup_period == current_period
    scoring_periods = get_remaining_scoring_periods(league, matchup_period) if use_remaining else get_matchup_scoring_periods(league, matchup_period)
    rosters = roster_overrides or {}
    players1 = [{**player, "future_only": use_remaining} for player in rosters.get(team1_id, inputs["players_by_team"].get(team1_id, []))]
    players2 = [{**player, "future_only": use_remaining} for player in rosters.get(team2_id, inputs["players_by_team"].get(team2_id, []))]
    actual1 = actual2 = None
    if use_remaining:
        actual_cache = inputs.setdefault("actual_by_week", {})
        if matchup_period not in actual_cache:
            actual_cache[matchup_period] = {
                team: row.get("totals") or row.get("stats") or {}
                for team, row in league_metadata.get_all_teams_stats_for_week(matchup_period).items()
            }
        actual1 = actual_cache[matchup_period].get(team1_id)
        actual2 = actual_cache[matchup_period].get(team2_id)
    effective_seed = seed if seed is not None else stable_seed(
        league_metadata.league_id, league_metadata.year, matchup_period,
        team1_id, team2_id, inputs["snapshot"].created_at.date(), ENGINE_VERSION,
    )
    result = simulate_matchup_odds(
        players1, players2, scoring_periods,
        actual1=actual1, actual2=actual2,
        categories=inputs["categories"], reverse_categories=inputs["reverse_categories"],
        slots=inputs["snapshot"].active_slots, trials=trials, seed=effective_seed,
        team1_id=team1_id, team2_id=team2_id,
        availability_overrides1=availability_overrides1,
        availability_overrides2=availability_overrides2,
        forced_lineups1=forced_lineups1,
        forced_lineups2=forced_lineups2,
    )
    profile = inputs.get("calibration") or {"temperature": 1.0, "applied": False, "sample_size": 0}
    temperature = float(profile.get("temperature", 1.0))
    if profile.get("applied") and temperature != 1.0:
        probabilities = [max(1e-9, float(result[key])) ** (1.0 / temperature) for key in ("p_win", "p_tie", "p_loss")]
        total = sum(probabilities)
        result.update(dict(zip(("p_win", "p_tie", "p_loss"), (value / total for value in probabilities))))
        result["monte_carlo_se"] = (result["p_win"] * (1.0 - result["p_win"]) / result["trials"]) ** 0.5
    result["calibration"] = profile
    result.update({
        "team1_name": inputs["teams"][team1_id].team_name,
        "team2_name": inputs["teams"][team2_id].team_name,
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "remaining_only": use_remaining,
        "data_as_of": inputs["snapshot"].created_at.isoformat(),
    })
    return result


def odds_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Return paired probability/category deltas from equal-seed simulations."""
    categories = {}
    for category in set(before.get("categories", {})) | set(after.get("categories", {})):
        old = before.get("categories", {}).get(category, {})
        new = after.get("categories", {}).get(category, {})
        categories[category] = {
            "p_win": round(float(new.get("p_win", 0.0)) - float(old.get("p_win", 0.0)), 4),
            "mean_margin": round(float(new.get("mean_margin", 0.0)) - float(old.get("mean_margin", 0.0)), 4),
        }
    return {
        "p_win": round(float(after.get("p_win", 0.0)) - float(before.get("p_win", 0.0)), 4),
        "p_tie": round(float(after.get("p_tie", 0.0)) - float(before.get("p_tie", 0.0)), 4),
        "p_loss": round(float(after.get("p_loss", 0.0)) - float(before.get("p_loss", 0.0)), 4),
        "categories": categories,
        "monte_carlo_se": round((float(before.get("monte_carlo_se", 0.0)) ** 2 + float(after.get("monte_carlo_se", 0.0)) ** 2) ** 0.5, 4),
    }


def optimize_lineup_by_win_probability(
    league_metadata,
    inputs: dict[str, Any],
    team_id: int,
    opponent_id: int,
    matchup_period: int,
    *,
    remaining_only: bool = True,
    trials: int = 100,
) -> dict[str, Any]:
    """Greedy day-by-day legal swaps evaluated by paired matchup simulations.

    We intentionally evaluate a bounded shortlist of exact starter sets.  This
    replaces the former whole-week player-removal proxy while keeping the API
    responsive for a seven-day matchup.
    """
    players = inputs["players_by_team"].get(team_id, [])
    league = league_metadata.league
    current = int(league.currentMatchupPeriod)
    use_remaining = remaining_only and matchup_period == current
    scoring_periods = get_remaining_scoring_periods(league, matchup_period) if use_remaining else get_matchup_scoring_periods(league, matchup_period)
    projection_players = [{**player, "future_only": use_remaining} for player in players]
    initial = build_matchup_lineups(projection_players, scoring_periods, slots=inputs["snapshot"].active_slots, fill_slots=True)

    def identity(player):
        return player.get("player_id") or player.get("name")

    forced = {
        int(day["scoring_period"]): [identity(item["player"]) for item in day["starters"]]
        for day in initial["days"]
    }
    seed = stable_seed(league_metadata.league_id, league_metadata.year, matchup_period, team_id, opponent_id, "lineup-v2")
    baseline = simulate_pair(
        league_metadata, inputs, team_id, opponent_id, matchup_period,
        remaining_only=remaining_only, trials=trials, seed=seed, forced_lineups1=forced,
    )
    current_odds = baseline
    day_results = []
    slots = inputs["snapshot"].active_slots

    for day in initial["days"]:
        scoring_period = int(day["scoring_period"])
        original_ids = tuple(forced[scoring_period])
        playing = [player for player in projection_players if has_game(player, scoring_period) and player.get("available", True)]
        by_id = {str(identity(player)): player for player in playing}
        original_set = {str(value) for value in original_ids}
        starters = [by_id[str(value)] for value in original_ids if str(value) in by_id]
        bench = [player for player in playing if str(identity(player)) not in original_set]
        options = {tuple(str(value) for value in original_ids): day["starters"]}
        ranked_swaps = []
        for incoming in bench:
            for outgoing in starters:
                pool = [player for player in starters if identity(player) != identity(outgoing)] + [incoming]
                optimized = optimize_daily_lineup(pool, slots=slots, fill_slots=True)
                if len(optimized["starters"]) != len(day["starters"]):
                    continue
                ids = tuple(str(identity(item["player"])) for item in optimized["starters"])
                if str(identity(incoming)) not in ids:
                    continue
                heuristic = player_value(incoming) - player_value(outgoing)
                ranked_swaps.append((heuristic, ids, optimized["starters"]))
        for _, ids, assignments in sorted(ranked_swaps, key=lambda row: row[0], reverse=True)[:10]:
            options.setdefault(ids, assignments)

        best_ids, best_assignments, best_odds = tuple(str(value) for value in original_ids), day["starters"], current_odds
        before_day = current_odds
        for ids, assignments in options.items():
            candidate_forced = {**forced, scoring_period: list(ids)}
            odds = simulate_pair(
                league_metadata, inputs, team_id, opponent_id, matchup_period,
                remaining_only=remaining_only, trials=trials, seed=seed, forced_lineups1=candidate_forced,
            )
            if (odds["p_win"], odds["p_tie"]) > (best_odds["p_win"], best_odds["p_tie"]):
                best_ids, best_assignments, best_odds = ids, assignments, odds
        forced[scoring_period] = list(best_ids)
        current_odds = best_odds
        chosen = {str(value) for value in best_ids}
        day_delta = odds_delta(before_day, best_odds)
        day_results.append({
            "scoring_period": scoring_period,
            "starters": [{
                "slot": item["slot"], "name": item["player"]["name"],
                "position": item["player"].get("position", "N/A"),
                "value": round(player_value(item["player"]), 4),
                "delta_p_win": day_delta["p_win"],
            } for item in best_assignments],
            "bench": [player["name"] for player in playing if str(identity(player)) not in chosen],
            "delta_p_win": day_delta["p_win"],
            "category_probability_delta": day_delta["categories"],
            "evaluated_lineups": len(options),
        })
    return {
        "days": day_results,
        "baseline_odds": baseline,
        "optimized_odds": current_odds,
        "delta": odds_delta(baseline, current_odds),
        "selected_games": {
            player["name"]: sum(str(identity(player)) in {str(value) for value in forced[day]} for day in forced)
            for player in players
        },
        "forced_lineups": forced,
    }


def get_matchup_odds(
    league_metadata,
    team_id: int,
    period: str,
    matchup_period: int | None = None,
    remaining_only: bool = True,
    trials: int = MATCHUP_MC_TRIALS,
) -> dict[str, Any]:
    matchup_period = matchup_period or int(league_metadata.league.currentMatchupPeriod)
    opponent_id = find_opponent(league_metadata, team_id, matchup_period)
    if opponent_id is None:
        raise ValueError("Matchup not found")
    cache = getattr(league_metadata, "_matchup_mc_cache", {})
    key = (team_id, opponent_id, matchup_period, period, remaining_only, max(100, min(trials, 5000)), str(league_metadata.last_refresh_time))
    cached = cache.get(key)
    if cached and monotonic() - cached[0] < 30:
        return cached[1]
    inputs = build_engine_inputs(league_metadata, period)
    result = simulate_pair(league_metadata, inputs, team_id, opponent_id, matchup_period, remaining_only=remaining_only, trials=trials)
    try:
        from .forecast_history import record
        expected = result.get("expected_stats") or [{}, {}]
        record(
            league_metadata.league_id, league_metadata.year, matchup_period, team_id, opponent_id,
            period, expected[0], expected[1], inputs["categories"], inputs["reverse_categories"], result,
        )
    except Exception:
        # Forecast persistence must never make a user-facing calculation fail.
        pass
    if len(cache) > 40:
        cache.clear()
    cache[key] = (monotonic(), result)
    league_metadata._matchup_mc_cache = cache
    return result
