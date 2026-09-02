"""Прогноз регулярного сезона на официальном ESPN schedule."""

from collections import defaultdict
from typing import Any, Dict

from core.projection import get_matchup_scoring_periods, project_team_stats
from core.simulation import compare_category_stats
from core.snapshot import build_league_snapshot
from services.projections import project_snapshot_for_matchup


def project_regular_season(league_metadata, period: str, calculation_engine: str = "calendar") -> Dict[str, Any]:
    league = league_metadata.league
    teams = league_metadata.get_teams()
    regular_season_end = int(league.settings.reg_season_count)
    current_period = int(league.currentMatchupPeriod)
    first_projection_period = min(current_period, regular_season_end + 1)

    records = {
        team.team_id: {
            "wins": int(getattr(team, "wins", 0) or 0),
            "losses": int(getattr(team, "losses", 0) or 0),
            "ties": int(getattr(team, "ties", 0) or 0),
        }
        for team in teams
    }
    projected_matchups = defaultdict(list)

    has_future_matchups = first_projection_period <= regular_season_end
    if has_future_matchups:
        snapshot = build_league_snapshot(league_metadata, period)
        legacy_team_stats = None
        if calculation_engine == "legacy":
            legacy_team_stats = {}
            for team in teams:
                players = [player.as_projection_player() for player in snapshot.team_players(team.team_id)]
                selected_games = {player["name"]: 1 for player in players if player.get("available", True)}
                legacy_team_stats[team.team_id] = {
                    "name": team.team_name,
                    "stats": project_team_stats(players, selected_games),
                }
        schedule = league_metadata.get_schedule_matchups(
            first_projection_period,
            regular_season_end,
        )
        schedule_by_period = defaultdict(list)
        for matchup in schedule:
            schedule_by_period[matchup["matchup_period"]].append(matchup)

        for matchup_period in range(first_projection_period, regular_season_end + 1):
            scoring_periods = get_matchup_scoring_periods(league, matchup_period)
            if legacy_team_stats is not None:
                team_stats = legacy_team_stats
            else:
                team_stats, _ = project_snapshot_for_matchup(snapshot, teams, scoring_periods)
            for matchup in schedule_by_period[matchup_period]:
                team1_id = matchup["team1_id"]
                team2_id = matchup["team2_id"]
                comparison = compare_category_stats(
                    team_stats[team1_id]["stats"],
                    team_stats[team2_id]["stats"],
                )
                wins1 = comparison["team1_wins"]
                wins2 = comparison["team2_wins"]
                if wins1 > wins2:
                    result1, result2 = "win", "loss"
                    records[team1_id]["wins"] += 1
                    records[team2_id]["losses"] += 1
                elif wins2 > wins1:
                    result1, result2 = "loss", "win"
                    records[team2_id]["wins"] += 1
                    records[team1_id]["losses"] += 1
                else:
                    result1 = result2 = "tie"
                    records[team1_id]["ties"] += 1
                    records[team2_id]["ties"] += 1

                projected_matchups[team1_id].append(
                    {"week": matchup_period, "opponent_id": team2_id, "result": result1, "score": f"{wins1}-{wins2}"}
                )
                projected_matchups[team2_id].append(
                    {"week": matchup_period, "opponent_id": team1_id, "result": result2, "score": f"{wins2}-{wins1}"}
                )

    standings = []
    teams_by_id = {team.team_id: team for team in teams}
    for team_id, record in records.items():
        total = record["wins"] + record["losses"] + record["ties"]
        win_rate = (record["wins"] + 0.5 * record["ties"]) / total if total else 0.0
        standings.append(
            {
                "team_id": team_id,
                "team_name": teams_by_id[team_id].team_name,
                "official_position": int(getattr(teams_by_id[team_id], "standing", 0) or 0),
                **record,
                "win_rate": round(win_rate * 100, 1),
                "projected_matchups": projected_matchups[team_id],
            }
        )

    if has_future_matchups:
        standings.sort(key=lambda item: (item["win_rate"], item["wins"]), reverse=True)
    else:
        standings.sort(key=lambda item: item["official_position"] or 10_000)
    for index, standing in enumerate(standings, start=1):
        standing["projected_position"] = index

    return {
        "period": period,
        "current_matchup_period": current_period,
        "regular_season_end": regular_season_end,
        "standings": standings,
        "tie_break_note": "Future ties are ordered by projected win rate and wins; ESPN applies the configured league tie-breaker.",
        "method": "legacy_team_averages" if calculation_engine == "legacy" else "schedule_projection",
    }
