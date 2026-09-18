"""Team-specific free-agent recommendations and bounded streaming plans."""

from datetime import date, timedelta

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
from core.player_rates import build_player_rate
from services.matchup_engine import build_engine_inputs, odds_delta, simulate_pair


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
    calculation_engine: str = "calendar",
    max_transactions: int = 2,
    acquisitions_remaining: int = 2,
    waiver_delay_days: int = 0,
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
        rate = build_player_rate(projection_player)
        projection_player.update({"rate": rate.as_dict(), "stats": rate.mean, "p_play": rate.p_play})
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
    response = {
        "team_id": team_id,
        "period": period,
        "matchup_period": matchup_period,
        "scoring_periods": scoring_periods,
        "baseline_selected_games": sum(baseline_games.values()),
        "method": "opponent_category_utility" if opponent is not None else "marginal_daily_lineup_value",
        "note": "Сравнение одиночных замен после фактического счёта; эффект — эвристика категорий, не вероятность победы. Защищены травмированные и верхняя половина состава. Проверьте waiver-срок и лимит добавлений в ESPN.",
        "players": recommendations[:limit],
    }
    if calculation_engine != "probabilistic" or not box:
        return response

    max_steps = min(max(0, int(max_transactions)), max(0, int(acquisitions_remaining)), 3)
    if max_steps == 0 or not recommendations:
        response.update({
            "method": "probabilistic_streaming_plan",
            "transaction_plans": [],
            "note": "Лимит доступных добавлений исчерпан; рекомендаций на транзакцию нет.",
        })
        return response

    inputs = build_engine_inputs(league_metadata, period)
    opponent_id = int(box["opponent_id"])
    seed = None
    baseline_odds = simulate_pair(
        league_metadata, inputs, team_id, opponent_id, matchup_period,
        remaining_only=True, trials=100,
    )
    seed = baseline_odds["seed"]
    candidates_by_name = {player["name"]: player for player in free_agents}
    initial_roster = list(inputs["players_by_team"].get(team_id, []))
    weakest_drops = sorted(drop_pool, key=lambda player: season_values.get(player["name"], player_value(player, punt_categories)))[:3]
    action_pool = [
        {**item, "drop_player": dropped["name"]}
        for item in recommendations[:6]
        if item["name"] in candidates_by_name
        for dropped in weakest_drops
    ]

    def roster_after(current_roster, action, step):
        names = {player["name"] for player in current_roster}
        if action["drop_player"] not in names or action["name"] in names:
            return None
        effective = date.today() + timedelta(days=max(0, int(waiver_delay_days)))
        added = {**candidates_by_name[action["name"]], "available_from": effective.isoformat()}
        return [player for player in current_roster if player["name"] != action["drop_player"]] + [added]

    beam = [({"roster": initial_roster, "actions": [], "odds": baseline_odds}, 0.0)]
    completed = []
    for step in range(1, max_steps + 1):
        expanded = []
        for state, _ in beam:
            used = {item["name"] for item in state["actions"]}
            for action in action_pool:
                if action["name"] in used:
                    continue
                changed = roster_after(state["roster"], action, step)
                if changed is None:
                    continue
                odds = simulate_pair(
                    league_metadata, inputs, team_id, opponent_id, matchup_period,
                    remaining_only=True, trials=100, seed=seed,
                    roster_overrides={team_id: changed},
                )
                actions = state["actions"] + [{
                    "order": step, "add": action["name"], "drop": action["drop_player"],
                    "available_from": next(player["available_from"] for player in changed if player["name"] == action["name"]),
                }]
                ros_delta = sum(
                    candidates_by_name[item["add"]].get("base_value", 0.0) - season_values.get(item["drop"], 0.0)
                    for item in actions
                )
                score = float(odds["p_win"]) + 0.002 * ros_delta
                expanded.append(({"roster": changed, "actions": actions, "odds": odds, "ros_delta": ros_delta}, score))
        if not expanded:
            break
        beam = sorted(expanded, key=lambda row: row[1], reverse=True)[:5]
        completed.extend(state for state, _ in beam)

    plans = []
    for state in sorted(completed, key=lambda item: (item["odds"]["p_win"], item.get("ros_delta", 0.0)), reverse=True)[:5]:
        delta = odds_delta(baseline_odds, state["odds"])
        plans.append({
            "actions": state["actions"],
            "p_win_before": baseline_odds["p_win"], "p_win_after": state["odds"]["p_win"],
            "delta_p_win": delta["p_win"], "rest_of_season_value_delta": round(state.get("ros_delta", 0.0), 3),
            "category_probability_delta": delta["categories"],
        })
    best_by_add = {}
    for plan in plans:
        if len(plan["actions"]) == 1:
            best_by_add[plan["actions"][0]["add"]] = plan
    for item in recommendations:
        plan = best_by_add.get(item["name"])
        if plan:
            item.update({
                "delta_p_win": plan["delta_p_win"],
                "p_win_after": plan["p_win_after"],
                "category_probability_delta": plan["category_probability_delta"],
                "rest_of_season_value_delta": plan["rest_of_season_value_delta"],
            })
    recommendations.sort(key=lambda item: (item.get("delta_p_win", -1.0), item.get("rest_of_season_value_delta", -999.0)), reverse=True)
    response.update({
        "method": "probabilistic_streaming_plan",
        "baseline_odds": baseline_odds,
        "transaction_plans": plans,
        "constraints": {
            "max_transactions": max_steps, "acquisitions_remaining": acquisitions_remaining,
            "waiver_delay_days": waiver_delay_days,
        },
        "note": "Планы сравниваются общим seed по ΔP(win), учитывают лимит транзакций, задержку waiver, lineup slots и стоимость отчисляемых игроков до конца сезона.",
        "players": recommendations[:limit],
    })
    return response
