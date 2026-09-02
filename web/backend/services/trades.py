"""Schedule and lineup aware trade impact."""

from core.config import CATEGORIES
from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    project_team_stats,
)
from core.snapshot import build_league_snapshot


def _project(players, scoring_periods, punts):
    lineup = build_matchup_lineups(players, scoring_periods, punt_categories=punts)
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
        player.name: player.as_projection_player()
        for player in snapshot.players
    }
    teams = {}
    for team_id, move in team_moves.items():
        before = [player.as_projection_player() for player in snapshot.team_players(team_id)]
        after = [player for player in before if player["name"] not in move["give"]]
        after.extend(all_players[name] for name in move["receive"] if name in all_players)
        before_value, before_stats, before_games = _project(before, scoring_periods, punt_categories)
        after_value, after_stats, after_games = _project(after, scoring_periods, punt_categories)
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
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "teams": teams,
    }
