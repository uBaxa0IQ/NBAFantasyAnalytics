"""Compatibility calculations for the original averages/Z-score engine."""

import math

from core.z_score import calculate_z_scores


PERCENTAGE_CATEGORIES = {"FG%", "FT%", "3PT%"}


def _matchup_bonus(player, team_stats, opponent_stats, punts):
    bonus = 0.0
    details = {}
    for category, player_z in player.get("z_scores", {}).items():
        if category in punts:
            continue
        team_value = float(team_stats.get(category, 0) or 0)
        opponent_value = float(opponent_stats.get(category, 0) or 0)
        if category in PERCENTAGE_CATEGORIES:
            team_value = team_value / 100 if team_value > 1 else team_value
            opponent_value = opponent_value / 100 if opponent_value > 1 else opponent_value
        category_bonus = 0.0
        reason = "Нейтрально"
        if opponent_value > team_value and team_value > 0:
            difference = (opponent_value - team_value) / team_value
            if difference <= 0.2:
                category_bonus = player_z * (1 + difference * 5)
                reason = f"Отставание {difference * 100:.1f}%"
            else:
                reason = "Категория далеко"
        elif opponent_value and team_value > opponent_value * 1.2:
            category_bonus = -player_z * 0.3
            reason = "Уверенное преимущество"
        bonus += category_bonus
        details[category] = {"bonus": category_bonus, "reason": reason}
    return bonus, details


def rank_lineup_legacy(league_metadata, team_id, period, punts=()):
    team = league_metadata.get_team_by_id(team_id)
    if team is None:
        raise ValueError("Team not found")
    z_data = calculate_z_scores(league_metadata, period)
    z_by_name = {player["name"]: player["z_scores"] for player in z_data["players"]}
    players = []
    for player in league_metadata.get_team_roster(team_id):
        if getattr(player, "lineupSlot", "") == "IR":
            continue
        if getattr(player, "injured", False) and getattr(player, "injuryStatus", "") == "OUT":
            continue
        players.append({
            "name": player.name,
            "position": getattr(player, "position", "N/A"),
            "z_scores": z_by_name.get(player.name, {}),
        })

    matchup_period = int(league_metadata.league.currentMatchupPeriod)
    matchup = league_metadata.get_matchup_box_score(matchup_period, team_id)
    team_stats, opponent_stats = {}, {}
    matchup_info = None
    if matchup:
        opponent_id = matchup["opponent_id"]
        summary = league_metadata.get_matchup_summary(matchup_period, team_id, opponent_id)
        if summary:
            if summary["team1_id"] == team_id:
                team_stats = summary["team1_stats_filtered"]
                opponent_stats = summary["team2_stats_filtered"]
            else:
                team_stats = summary["team2_stats_filtered"]
                opponent_stats = summary["team1_stats_filtered"]
        matchup_info = {
            "opponent_name": matchup["opponent_name"],
            "opponent_id": opponent_id,
            "week": matchup_period,
        }

    ranked = []
    for player in players:
        base_z = sum(value for category, value in player["z_scores"].items() if category not in punts and math.isfinite(value))
        matchup_bonus, category_details = _matchup_bonus(player, team_stats, opponent_stats, punts)
        ranked.append({
            "name": player["name"],
            "position": player["position"],
            "value": base_z + matchup_bonus,
            "base_z": base_z,
            "matchup_bonus": matchup_bonus,
            "category_details": category_details,
        })
    ranked.sort(key=lambda player: player["value"], reverse=True)
    return {
        "method": "legacy_matchup_z_ranking",
        "players": ranked,
        "total_players": len(ranked),
        "matchup_info": matchup_info,
    }
