"""ESPN adapter for the pure probabilistic core."""

from __future__ import annotations

from time import monotonic
from collections import defaultdict
from statistics import stdev
from math import isfinite
from typing import Any, Mapping

from core.config import MATCHUP_MC_TRIALS, PERIODS
from core.matchup_mc import ENGINE_VERSION, simulate_matchup_odds, stable_seed
from core.player_rates import attach_player_rates
from core.projection import get_matchup_scoring_periods, get_remaining_scoring_periods
from core.snapshot import build_league_snapshot


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
) -> dict[str, Any]:
    league = league_metadata.league
    current_period = int(league.currentMatchupPeriod)
    use_remaining = remaining_only and matchup_period == current_period
    scoring_periods = get_remaining_scoring_periods(league, matchup_period) if use_remaining else get_matchup_scoring_periods(league, matchup_period)
    players1 = [{**player, "future_only": use_remaining} for player in inputs["players_by_team"].get(team1_id, [])]
    players2 = [{**player, "future_only": use_remaining} for player in inputs["players_by_team"].get(team2_id, [])]
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
    )
    result.update({
        "team1_name": inputs["teams"][team1_id].team_name,
        "team2_name": inputs["teams"][team2_id].team_name,
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "remaining_only": use_remaining,
        "data_as_of": inputs["snapshot"].created_at.isoformat(),
    })
    return result


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
