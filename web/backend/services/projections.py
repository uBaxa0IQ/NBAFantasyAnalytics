"""Оркестрация snapshot и projection engine для API."""

from typing import Any, Dict, Iterable, Optional

from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    project_team_stats,
)
from core.snapshot import build_league_snapshot
from core.simulation import simulate_all_vs_all
from core.matchup_value import combine_stats, add_matchup_values


def project_team_matchup(
    league_metadata,
    team_id: int,
    period: str,
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: Iterable[str] = (),
) -> Dict[str, Any]:
    league = league_metadata.league
    matchup_period = matchup_period or int(league.currentMatchupPeriod)
    snapshot = build_league_snapshot(league_metadata, period)
    team = league_metadata.get_team_by_id(team_id)
    if team is None:
        raise ValueError("Team not found")

    player_snapshots = snapshot.team_players(team_id)
    players = [{**player.as_projection_player(), 'future_only': remaining_only} for player in player_snapshots]
    if remaining_only:
        scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    else:
        scoring_periods = get_matchup_scoring_periods(league, matchup_period)

    opponent = None
    if remaining_only:
        box = league_metadata.get_matchup_box_score(matchup_period, team_id)
        if box:
            opponent_players = [{**p.as_projection_player(), 'future_only': True} for p in snapshot.team_players(box['opponent_id'])]
            opponent_lineup = build_matchup_lineups(opponent_players, scoring_periods, snapshot.active_slots, punt_categories)
            opponent_box = league_metadata.get_matchup_box_score(matchup_period, box['opponent_id'])
            if opponent_box:
                opponent = combine_stats(opponent_box['totals'], project_team_stats(opponent_players, opponent_lineup['selected_games']))
                baseline = build_matchup_lineups(players, scoring_periods, snapshot.active_slots, punt_categories)
                baseline_stats = combine_stats(box['totals'], project_team_stats(players, baseline['selected_games']))
                players = add_matchup_values(players, baseline_stats, opponent, punt_categories)
    lineup = build_matchup_lineups(players, scoring_periods, slots=snapshot.active_slots, punt_categories=punt_categories, fill_slots=opponent is None)
    projected_stats = project_team_stats(players, lineup["selected_games"])

    days = []
    for day in lineup["days"]:
        days.append(
            {
                "scoring_period": day["scoring_period"],
                "starters": [
                    {
                        "slot": starter["slot"],
                        "name": starter["player"]["name"],
                        "position": starter["player"]["position"],
                        "value": round(starter["value"], 3),
                    }
                    for starter in day["starters"]
                ],
                "bench": [player["name"] for player in day["bench"]],
            }
        )

    return {
        "team_id": team_id,
        "team_name": team.team_name,
        "period": period,
        "matchup_period": matchup_period,
        "remaining_only": remaining_only,
        "scoring_periods": scoring_periods,
        "projected_stats": projected_stats,
        "selected_games": lineup["selected_games"],
        "days": days,
        "snapshot_created_at": snapshot.created_at.isoformat(),
        "objective": 'opponent_category_utility' if opponent is not None else 'games_then_z',
        "note": "Подбор по предельному вкладу в категории соперника; эвристика, не гарантия победы. Начавшиеся игры исключены из будущей статистики.",
    }


def project_league_matchup(
    league_metadata,
    period: str,
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: Iterable[str] = (),
) -> Dict[str, Any]:
    league = league_metadata.league
    matchup_period = matchup_period or int(league.currentMatchupPeriod)
    snapshot = build_league_snapshot(league_metadata, period)
    scoring_periods = (
        get_remaining_scoring_periods(league, matchup_period)
        if remaining_only
        else get_matchup_scoring_periods(league, matchup_period)
    )

    team_stats, team_projections = project_snapshot_for_matchup(
        snapshot,
        league_metadata.get_teams(),
        scoring_periods,
        punt_categories,
        future_only=remaining_only,
    )

    return {
        "mode": "schedule_projection",
        "period": period,
        "matchup_period": matchup_period,
        "remaining_only": remaining_only,
        "scoring_periods": scoring_periods,
        "results": simulate_all_vs_all(team_stats),
        "team_projections": team_projections,
        "snapshot_created_at": snapshot.created_at.isoformat(),
    }


def project_snapshot_for_matchup(snapshot, teams, scoring_periods, punt_categories=(), future_only=False):
    """Проецирует все команды из одного snapshot для заданных scoring days."""
    team_stats = {}
    team_projections = {}
    for team in teams:
        players = [
            {**player.as_projection_player(), 'future_only': future_only}
            for player in snapshot.team_players(team.team_id)
        ]
        lineup = build_matchup_lineups(players, scoring_periods, slots=snapshot.active_slots, punt_categories=punt_categories)
        stats = project_team_stats(players, lineup["selected_games"])
        team_stats[team.team_id] = {"name": team.team_name, "stats": stats}
        team_projections[team.team_id] = {
            "selected_games": lineup["selected_games"],
            "total_selected_games": sum(lineup["selected_games"].values()),
        }
    return team_stats, team_projections
