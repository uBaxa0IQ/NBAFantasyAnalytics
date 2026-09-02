"""Team-specific free-agent recommendations."""

from core.config import CATEGORIES
from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    player_value,
    project_team_stats,
)
from core.snapshot import build_league_snapshot
from core.z_score import calculate_player_z_scores


def _lineup_projection(players, scoring_periods, punts):
    lineup = build_matchup_lineups(players, scoring_periods, punt_categories=punts)
    return (
        sum(day["total_value"] for day in lineup["days"]),
        project_team_stats(players, lineup["selected_games"]),
        lineup["selected_games"],
    )


def recommend_free_agents(
    league_metadata,
    team_id: int,
    period: str,
    position: str | None = None,
    punt_categories=(),
    limit: int = 30,
):
    snapshot = build_league_snapshot(league_metadata, period)
    roster = [player.as_projection_player() for player in snapshot.team_players(team_id)]
    if not roster:
        raise ValueError("Team not found or roster is empty")

    league = league_metadata.league
    matchup_period = int(league.currentMatchupPeriod)
    scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    if not scoring_periods:
        scoring_periods = get_matchup_scoring_periods(league, matchup_period)

    baseline_value, baseline_stats, baseline_games = _lineup_projection(
        roster, scoring_periods, punt_categories
    )
    free_agents = []
    free_agent_summaries = league_metadata.get_free_agents(size=200, position=position)
    player_ids = [getattr(player, "playerId", None) for player in free_agent_summaries]
    player_ids = [player_id for player_id in player_ids if player_id is not None]
    hydrated = league.player_info(playerId=player_ids) if player_ids else []
    if hydrated and not isinstance(hydrated, list):
        hydrated = [hydrated]
    # free_agents() omits pro_schedule; player_info() restores the 82-game map
    # required by the calendar optimizer.
    candidate_source = hydrated or free_agent_summaries
    for player in candidate_source:
        stats = league_metadata.get_player_stats(player, period, "avg")
        if not stats:
            continue
        projection_player = {
            "player_id": getattr(player, "playerId", None),
            "name": player.name,
            "position": getattr(player, "position", "N/A"),
            "eligible_slots": getattr(player, "eligibleSlots", []),
            "schedule": getattr(player, "schedule", {}),
            "stats": stats,
            "z_scores": calculate_player_z_scores(stats, snapshot.league_metrics),
            "available": not (
                getattr(player, "injured", False)
                and getattr(player, "injuryStatus", "ACTIVE") == "OUT"
            ),
            "injured": getattr(player, "injured", False),
            "injury_status": getattr(player, "injuryStatus", "ACTIVE"),
            "nba_team": getattr(player, "proTeam", "N/A"),
        }
        projection_player["base_value"] = player_value(projection_player, punt_categories)
        free_agents.append(projection_player)

    # Calendar evaluation is intentionally limited to plausible adds. This keeps the
    # endpoint responsive while the full list remains available in /free-agents.
    candidates = sorted(free_agents, key=lambda item: item["base_value"], reverse=True)[:60]
    drop_pool = sorted(
        roster,
        key=lambda item: (item.get("available", True), player_value(item, punt_categories)),
    )[:7]

    recommendations = []
    for candidate in candidates:
        best = None
        for dropped in drop_pool:
            changed_roster = [player for player in roster if player["name"] != dropped["name"]]
            changed_roster.append(candidate)
            value, projected_stats, selected_games = _lineup_projection(
                changed_roster, scoring_periods, punt_categories
            )
            gain = value - baseline_value
            player_games_delta = sum(selected_games.values()) - sum(baseline_games.values())
            comparison_key = (player_games_delta, gain)
            if best is None or comparison_key > best["comparison_key"]:
                best = {
                    "drop_player": dropped["name"],
                    "lineup_gain": gain,
                    "player_games_delta": player_games_delta,
                    "projected_stats": projected_stats,
                    "selected_games": selected_games.get(candidate["name"], 0),
                    "comparison_key": comparison_key,
                }
        if best is None or best["selected_games"] <= 0:
            continue
        recommendation = {
            "player_id": candidate.get("player_id"),
            "name": candidate["name"],
            "position": candidate["position"],
            "nba_team": candidate["nba_team"],
            "injury_status": candidate["injury_status"],
            "z_scores": candidate["z_scores"],
            "stats": candidate["stats"],
            "base_value": round(candidate["base_value"], 3),
            "lineup_gain": round(best["lineup_gain"], 3),
            "player_games_delta": best["player_games_delta"],
            "drop_player": best["drop_player"],
            "selected_games": best["selected_games"],
            "category_delta": {
                category: round(best["projected_stats"].get(category, 0) - baseline_stats.get(category, 0), 4)
                for category in CATEGORIES
                if category not in punt_categories
            },
        }
        recommendations.append(recommendation)

    recommendations.sort(
        key=lambda item: (item["player_games_delta"], item["lineup_gain"]),
        reverse=True,
    )
    return {
        "team_id": team_id,
        "period": period,
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "baseline_selected_games": sum(baseline_games.values()),
        "method": "marginal_daily_lineup_value",
        "players": recommendations[:limit],
    }
