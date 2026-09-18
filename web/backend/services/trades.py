"""Schedule, lineup and probability aware trade impact."""

from datetime import date, timedelta

from core.config import CATEGORIES
from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    project_team_stats,
)
from core.snapshot import build_league_snapshot
from core.projection import player_value
from services.matchup_engine import build_engine_inputs, find_opponent, odds_delta, simulate_pair
from services.season import project_regular_season_probabilistic


def _project(players, scoring_periods, punts, slots):
    lineup = build_matchup_lineups(players, scoring_periods, slots=slots, punt_categories=punts)
    stats = project_team_stats(players, lineup["selected_games"])
    value = sum(day["total_value"] for day in lineup["days"])
    return value, stats, sum(lineup["selected_games"].values())


def analyze_calendar_trade(league_metadata, period, team_moves, punt_categories=()):
    """Evaluate roster moves in the actual remaining matchup calendar."""
    snapshot = build_league_snapshot(league_metadata, period)
    league = league_metadata.league
    matchup_period = int(league.currentMatchupPeriod)
    scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    if not scoring_periods:
        scoring_periods = get_matchup_scoring_periods(league, matchup_period)

    all_players = {
        player.name: {**player.as_projection_player(), 'future_only': True}
        for player in snapshot.players
    }
    teams = {}
    for team_id, move in team_moves.items():
        before = [{**player.as_projection_player(), 'future_only': True} for player in snapshot.team_players(team_id)]
        after = [player for player in before if player["name"] not in move["give"]]
        after.extend(all_players[name] for name in move["receive"] if name in all_players)
        before_value, before_stats, before_games = _project(before, scoring_periods, punt_categories, snapshot.active_slots)
        after_value, after_stats, after_games = _project(after, scoring_periods, punt_categories, snapshot.active_slots)
        teams[team_id] = {
            "before_value": round(before_value, 3),
            "after_value": round(after_value, 3),
            "delta": round(after_value - before_value, 3),
            "selected_games_before": before_games,
            "selected_games_after": after_games,
            "category_delta": {
                category: round(after_stats.get(category, 0) - before_stats.get(category, 0), 4)
                for category in CATEGORIES
                if category not in punt_categories
            },
        }
    return {
        "method": "remaining_calendar_and_daily_slots",
        "scope_note": "Календарная дельта относится только к текущему матчапу. Для долгосрочного обмена сравните также статистику состава за сезон.",
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "teams": teams,
    }


def _replacement_player(roster, index: int):
    """Conservative replacement-level roster spot for an uneven trade."""
    weakest = min(roster, key=player_value)
    rate = weakest.get("rate") or {}
    replacement_mean = {
        key: float(value) * .75 if isinstance(value, (int, float)) else value
        for key, value in (rate.get("mean") or weakest.get("stats") or {}).items()
    }
    replacement = {
        **weakest,
        "player_id": f"replacement-{index}",
        "name": f"Replacement-level FA {index}",
        "position": "UT",
        "eligible_slots": ["PG", "SG", "SF", "PF", "C", "G", "F", "UT"],
        "injured": False,
        "injury_status": "ACTIVE",
        "p_play": 1.0,
        "lineup_slot": "BE",
        "stats": replacement_mean,
        "rate": {**rate, "mean": replacement_mean, "p_play": 1.0},
        "z_scores": {
            key: float(value) * .75 if isinstance(value, (int, float)) else value
            for key, value in (weakest.get("z_scores") or {}).items()
        },
    }
    return replacement


def analyze_probabilistic_trade(
    league_metadata,
    period,
    team_moves,
    punt_categories=(),
    processing_delay_days: int = 0,
):
    """Evaluate both sides against current opponents and the remaining season."""
    inputs = build_engine_inputs(league_metadata, period)
    all_players = {
        player["name"]: player
        for roster in inputs["players_by_team"].values()
        for player in roster
    }
    effective_date = date.today() + timedelta(days=max(0, int(processing_delay_days)))
    after_rosters = {}
    roster_adjustments = {}
    for team_id, move in team_moves.items():
        team_id = int(team_id)
        before = list(inputs["players_by_team"].get(team_id, []))
        received_names = set(move.get("receive", ()))
        after = [player for player in before if player["name"] not in set(move.get("give", ()))]
        for name in received_names:
            if name in all_players:
                after.append({**all_players[name], "available_from": effective_date.isoformat()})
        auto_drops = []
        while len(after) > len(before):
            choices = [player for player in after if player["name"] not in received_names] or after
            dropped = min(choices, key=player_value)
            auto_drops.append(dropped["name"])
            after.remove(dropped)
        replacements = []
        while len(after) < len(before) and after:
            replacement = _replacement_player(after, len(replacements) + 1)
            replacements.append(replacement["name"])
            after.append(replacement)
        after_rosters[team_id] = after
        roster_adjustments[team_id] = {"auto_drops": auto_drops, "replacement_adds": replacements}

    current_period = int(league_metadata.league.currentMatchupPeriod)
    team_results = {}
    for team_id in after_rosters:
        opponent_id = find_opponent(league_metadata, team_id, current_period)
        if opponent_id is None:
            continue
        baseline = simulate_pair(
            league_metadata, inputs, team_id, opponent_id, current_period,
            remaining_only=True, trials=180,
        )
        after = simulate_pair(
            league_metadata, inputs, team_id, opponent_id, current_period,
            remaining_only=True, trials=180, seed=baseline["seed"],
            roster_overrides=after_rosters,
        )
        team_results[team_id] = {
            "opponent_id": opponent_id,
            "p_win_before": baseline["p_win"], "p_win_after": after["p_win"],
            "current_matchup_delta": odds_delta(baseline, after),
            "roster_adjustments": roster_adjustments[team_id],
        }

    before_season = project_regular_season_probabilistic(
        league_metadata, period, pair_trials=100, season_trials=300, persist_forecasts=False,
    )
    after_season = project_regular_season_probabilistic(
        league_metadata, period, roster_overrides=after_rosters,
        pair_trials=100, season_trials=300, persist_forecasts=False,
    )
    before_by_team = {row["team_id"]: row for row in before_season["standings"]}
    after_by_team = {row["team_id"]: row for row in after_season["standings"]}
    for team_id, result in team_results.items():
        old, new = before_by_team.get(team_id, {}), after_by_team.get(team_id, {})
        result["season"] = {
            "p_playoff_before": old.get("p_playoff"), "p_playoff_after": new.get("p_playoff"),
            "delta_p_playoff": round(float(new.get("p_playoff", 0.0)) - float(old.get("p_playoff", 0.0)), 4),
            "p_title_before": old.get("p_title"), "p_title_after": new.get("p_title"),
            "delta_p_title": round(float(new.get("p_title", 0.0)) - float(old.get("p_title", 0.0)), 4),
        }
    return {
        "method": "probabilistic_trade_mc",
        "scope_note": "Обе стороны оценены общими сценариями текущего матчапа и остатка регулярного сезона; 2-for-1 включает обязательный дроп или replacement-level место.",
        "matchup_period": current_period,
        "processing_date": effective_date.isoformat(),
        "teams": team_results,
        "season_trials": 300,
    }
