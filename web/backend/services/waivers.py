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
from core.z_score import calculate_player_z_scores, calculate_z_scores_from_players
from core.matchup_value import combine_stats, matchup_utility, add_matchup_values


def _lineup_projection(players, scoring_periods, punts, slots, opponent=None, accrued=None):
    if opponent is not None:
        initial = build_matchup_lineups(players, scoring_periods, slots=slots, punt_categories=punts)
        baseline = combine_stats(accrued or {}, project_team_stats(players, initial['selected_games']))
        players = add_matchup_values(players, baseline, opponent, punts)
    lineup = build_matchup_lineups(players, scoring_periods, slots=slots, punt_categories=punts, fill_slots=opponent is None)
    return (
        sum(player_value({k: v for k, v in player.items() if k != 'lineup_value'}, punts) * lineup['selected_games'].get(player['name'], 0) for player in players),
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
    roster = [{**player.as_projection_player(), 'future_only': True} for player in snapshot.team_players(team_id)]
    if not roster:
        raise ValueError("Team not found or roster is empty")

    league = league_metadata.league
    matchup_period = int(league.currentMatchupPeriod)
    scoring_periods = get_remaining_scoring_periods(league, matchup_period)
    if not scoring_periods:
        return {'team_id': team_id, 'players': [], 'scoring_periods': [], 'method': 'season_complete', 'note': 'Нет оставшихся игровых дней.'}

    box = league_metadata.get_matchup_box_score(matchup_period, team_id)
    accrued = box['totals'] if box else {}
    opponent = None
    if box:
        opponent_players = [{**p.as_projection_player(), 'future_only': True} for p in snapshot.team_players(box['opponent_id'])]
        _, opponent_future, _ = _lineup_projection(opponent_players, scoring_periods, punt_categories, snapshot.active_slots)
        opponent_box = league_metadata.get_matchup_box_score(matchup_period, box['opponent_id'])
        if opponent_box:
            opponent = combine_stats(opponent_box['totals'], opponent_future)

    baseline_value, baseline_stats, baseline_games = _lineup_projection(
        roster, scoring_periods, punt_categories, snapshot.active_slots, opponent, accrued
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
            "future_only": True,
        }
        projection_player["base_value"] = player_value(projection_player, punt_categories)
        free_agents.append(projection_player)

    candidates = [player for player in free_agents if player['available']]
    # Preserve injured assets and the upper half of the roster by season value.
    season_players = league_metadata.get_all_players_stats(f'{league_metadata.year}_total', 'avg')
    season_metrics = calculate_z_scores_from_players(season_players)['league_metrics'] if season_players else snapshot.league_metrics
    season_values = {p['name']: sum(calculate_player_z_scores(p['stats'], season_metrics).get(c, 0) for c in CATEGORIES if c not in punt_categories) for p in season_players}
    ordered = sorted(roster, key=lambda p: season_values.get(p['name'], player_value(p, punt_categories)), reverse=True)
    protected = {p['name'] for p in ordered[:len(ordered) // 2]}
    drop_pool = [p for p in roster if p['available'] and not p.get('injured') and p['name'] not in protected]
    baseline_fit = matchup_utility(combine_stats(accrued, baseline_stats), opponent, punt_categories) if opponent is not None else baseline_value

    recommendations = []
    for candidate in candidates:
        best = None
        for dropped in drop_pool:
            changed_roster = [player for player in roster if player["name"] != dropped["name"]]
            changed_roster.append(candidate)
            value, projected_stats, selected_games = _lineup_projection(
                changed_roster, scoring_periods, punt_categories, snapshot.active_slots, opponent, accrued
            )
            gain = value - baseline_value
            player_games_delta = sum(selected_games.values()) - sum(baseline_games.values())
            fit_gain = (matchup_utility(combine_stats(accrued, projected_stats), opponent, punt_categories) if opponent is not None else value) - baseline_fit
            comparison_key = (fit_gain, gain, player_games_delta)
            if best is None or comparison_key > best["comparison_key"]:
                best = {
                    "drop_player": dropped["name"],
                    "lineup_gain": gain,
                    "matchup_gain": fit_gain,
                    "player_games_delta": player_games_delta,
                    "projected_stats": projected_stats,
                    "selected_games": selected_games.get(candidate["name"], 0),
                    "comparison_key": comparison_key,
                }
        if best is None or best["selected_games"] <= 0 or best['matchup_gain'] <= 0:
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
            "matchup_gain": round(best['matchup_gain'], 4),
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
        key=lambda item: (item['matchup_gain'], item["lineup_gain"], item["player_games_delta"]),
        reverse=True,
    )
    return {
        "team_id": team_id,
        "period": period,
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "baseline_selected_games": sum(baseline_games.values()),
        "method": "opponent_category_utility" if opponent is not None else "marginal_daily_lineup_value",
        "note": "Сравнение одиночных замен после фактического счёта; эффект — эвристика категорий, не вероятность победы. Защищены травмированные и верхняя половина состава. Проверьте waiver-срок и лимит добавлений в ESPN.",
        "players": recommendations[:limit],
    }
