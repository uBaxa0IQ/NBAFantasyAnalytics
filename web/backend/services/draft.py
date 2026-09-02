"""Read-only live draft state and recommendations."""

from collections import Counter, defaultdict
from itertools import combinations
from datetime import datetime, timezone

from espn_api.basketball.player import Player

from core.config import CATEGORIES, PERIODS
from core.z_score import calculate_player_z_scores, calculate_z_scores_from_players
from .draft_simulation import _evaluate_rosters, annotate_availability, simulate_draft_market
from .draft_advisor import (
    apply_pick_scores,
    build_pick_advice,
    build_scoring_context,
    lookahead_rerank,
)
from .espn_market import attach_market, get_espn_market
from .draft_live import overlay_live_draft


_previous_stats_cache = {}
_PREVIOUS_STATS_TTL_SECONDS = 6 * 60 * 60


def _team_names(league_metadata):
    return {team.team_id: team.team_name for team in league_metadata.get_teams()}


def _snake_team_at(pick_index, pick_order):
    if not pick_order:
        return None
    round_index, index_in_round = divmod(pick_index, len(pick_order))
    active_order = pick_order if round_index % 2 == 0 else list(reversed(pick_order))
    return active_order[index_in_round]


def _planned_team_picks(team_id, pick_order, rounds=14):
    """Возвращает номера выборов команды в snake-драфте."""
    if not pick_order or team_id not in pick_order:
        return []
    return [
        index + 1
        for index in range(len(pick_order) * rounds)
        if _snake_team_at(index, pick_order) == team_id
    ]


def _draft_round_count(raw_draft, team_count, fallback=14):
    """Infer the actual number of draft rounds, including ESPN empty slots."""
    picks = raw_draft.get("draftDetail", {}).get("picks", []) or []
    rounds = [
        int(pick.get("roundId"))
        for pick in picks
        if isinstance(pick.get("roundId"), int) and pick.get("roundId") > 0
    ]
    if rounds:
        return max(rounds)
    if team_count and picks and len(picks) % team_count == 0:
        return max(1, len(picks) // team_count)
    return fallback


def _active_picks(raw_draft):
    """ESPN иногда переносит прошлогодние пики в ещё не начавшийся сезон."""
    detail = raw_draft.get("draftDetail", {})
    picks = [
        pick for pick in (detail.get("picks", []) or [])
        if isinstance(pick.get("playerId"), int) and pick.get("playerId") > 0
    ]
    if detail.get("inProgress") or detail.get("drafted"):
        return picks
    return [pick for pick in picks if pick.get("keeper")]


def _season_has_activity(raw_league):
    """ESPN sets scoringPeriodId=1 before games; require actual matchup activity."""
    for matchup in raw_league.get("schedule", []) or []:
        if matchup.get("winner") not in (None, "UNDECIDED"):
            return True
        for side_name in ("home", "away"):
            side = matchup.get(side_name) or {}
            if (side.get("gamesPlayed") or 0) > 0 or (side.get("totalPoints") or 0) != 0:
                return True
            if any((value or 0) != 0 for value in (side.get("pointsByScoringPeriod") or {}).values()):
                return True
            score_by_stat = (side.get("cumulativeScore") or {}).get("scoreByStat") or {}
            for stat in score_by_stat.values():
                # ESPN pre-creates every matchup with result="TIE" and score=0.
                # That placeholder is not evidence that the season has started.
                if (stat.get("score") or 0) != 0:
                    return True
    return False


def _active_pick_order(raw_draft):
    """Не принимает прошлогодний pickOrder за очередь ещё не назначенного драфта."""
    detail = raw_draft.get("draftDetail", {})
    settings = raw_draft.get("settings", {}).get("draftSettings", {})
    pick_order = settings.get("pickOrder") or []
    draft_is_scheduled = settings.get("date") not in (None, 0, "")
    if detail.get("inProgress") or detail.get("drafted") or draft_is_scheduled:
        return pick_order
    return []


def _raw_average(player, period):
    data = (getattr(player, "stats", {}) or {}).get(period, {})
    stats = data.get("avg") if isinstance(data, dict) else None
    if not isinstance(stats, dict) or not stats:
        return None
    return {
        key: float(value) if value is not None else 0.0
        for key, value in stats.items()
        if isinstance(value, (int, float)) or value is None
    }


def _previous_season_stats(league_metadata, player_ids):
    """Load historical NBA stats through the current league player-card API."""
    if not player_ids or league_metadata.year <= 1:
        return {}
    try:
        previous_year = league_metadata.year - 1
        league = league_metadata.league
        unique_ids = [int(player_id) for player_id in dict.fromkeys(player_ids) if player_id]
        cache_key = (league_metadata.league_id, previous_year)
        now = datetime.now(timezone.utc)
        cached = _previous_stats_cache.get(cache_key)
        if not cached or (now - cached["saved_at"]).total_seconds() > _PREVIOUS_STATS_TTL_SECONDS:
            cached = {"saved_at": now, "requested": set(), "data": {}}
            _previous_stats_cache[cache_key] = cached

        missing_ids = [player_id for player_id in unique_ids if player_id not in cached["requested"]]
        for start in range(0, len(missing_ids), 50):
            batch = missing_ids[start:start + 50]
            raw = league.espn_request.get_player_card(
                batch,
                league.finalScoringPeriod,
                [f"00{previous_year}", f"10{previous_year}"],
            )
            cached["requested"].update(batch)
            for row in raw.get("players", []) or []:
                player = Player(row, previous_year)
                stats = _raw_average(player, f"{previous_year}_total")
                if stats and getattr(player, "playerId", None) is not None:
                    cached["data"][int(player.playerId)] = stats
        cached["saved_at"] = now
        return {
            player_id: cached["data"][player_id]
            for player_id in unique_ids
            if player_id in cached["data"]
        }
    except Exception as error:
        print(f"Не удалось загрузить статистику прошлого сезона: {error}")
        return {}


def _strategy_suggestions(category_strength, roster_size):
    """Строит несколько направлений состава без преждевременного жёсткого панта."""
    if not roster_size:
        return []

    averages = {
        category: value / roster_size
        for category, value in category_strength.items()
    }
    weakest = sorted(averages, key=averages.get)
    max_punts = min(3, max(1, roster_size // 2), len(weakest))
    candidates = [()] + [tuple(weakest[:count]) for count in range(1, max_punts + 1)]
    suggestions = []
    for punts in candidates:
        kept = [value for category, value in averages.items() if category not in punts]
        punt_values = [averages[category] for category in punts]
        retained_score = sum(kept) / len(kept) if kept else 0
        separation = retained_score - (sum(punt_values) / len(punt_values) if punt_values else retained_score)
        confidence = 0 if not punts else round(max(0, min(95, 38 + separation * 18)))
        # На первых пиках направление принципиально нестабильно.
        if roster_size < 3:
            confidence = min(confidence, 55)
        suggestions.append({
            "punt_categories": list(punts),
            "retained_score": round(retained_score, 3),
            "confidence": confidence,
            "confidence_label": (
                "открытая сборка" if not punts else
                "высокая" if confidence >= 75 else
                "средняя" if confidence >= 55 else
                "предварительная"
            ),
        })
    suggestions.sort(key=lambda item: (item["retained_score"], -len(item["punt_categories"])), reverse=True)
    return suggestions[:3]


def _roster_comparison(profiles, team_names, main_team_id, punt_categories=()):
    """Compare currently assembled rosters head-to-head across all categories."""
    eligible = {team_id: roster for team_id, roster in profiles.items() if roster}
    if main_team_id not in eligible or len(eligible) < 2:
        return None
    rows = []
    results = {}
    for compared_team_id in eligible:
        result = _evaluate_rosters(eligible, compared_team_id, punt_categories)
        results[compared_team_id] = result
        rows.append({
            "team_id": compared_team_id,
            "team_name": team_names.get(compared_team_id, f"Team {compared_team_id}"),
            "roster_size": len(eligible[compared_team_id]),
            "average_category_wins": round(result["category_wins"], 2),
            "league_rank": result["league_rank"],
        })
    rows.sort(key=lambda item: (item["league_rank"], -item["average_category_wins"]))
    main = results[main_team_id]
    return {
        "team_count": len(eligible),
        "average_category_wins": round(main["category_wins"], 2),
        "league_rank": main["league_rank"],
        "category_ranks": main["category_ranks"],
        "category_margin": {category: round(value, 2) for category, value in main["category_margin"].items()},
        "teams": rows,
    }


def _round_balanced_roster_comparison(
    profiles,
    team_names,
    main_team_id,
    pick_count,
    team_count,
    punt_categories=(),
):
    """Compare teams at the last boundary where every team had equal roster size."""
    completed_rounds = int(pick_count or 0) // max(1, int(team_count or 1))
    if completed_rounds <= 0:
        return {
            "completed_rounds": 0,
            "players_per_team": 0,
            "comparison": None,
        }

    balanced_profiles = {
        team_id: list(roster[:completed_rounds])
        for team_id, roster in profiles.items()
        if len(roster) >= completed_rounds
    }
    return {
        "completed_rounds": completed_rounds,
        "players_per_team": completed_rounds,
        "comparison": _roster_comparison(balanced_profiles, team_names, main_team_id, punt_categories),
    }


def get_draft_state(league_metadata):
    league = league_metadata.league
    raw = overlay_live_draft(league_metadata, league.espn_request.get_league_draft())
    detail = raw.get("draftDetail", {})
    settings = raw.get("settings", {}).get("draftSettings", {})
    team_names = _team_names(league_metadata)
    draft_rounds = _draft_round_count(raw, len(team_names))
    picks = []
    active_picks = _active_picks(raw)
    for pick in active_picks:
        player_id = pick.get("playerId")
        team_id = pick.get("teamId")
        picks.append({
            "overall": pick.get("overallPickNumber"),
            "round": pick.get("roundId"),
            "round_pick": pick.get("roundPickNumber"),
            "team_id": team_id,
            "team_name": team_names.get(team_id, f"Team {team_id}"),
            "player_id": player_id,
            "player_name": league.player_map.get(player_id, f"Player {player_id}"),
            "bid_amount": pick.get("bidAmount"),
            "keeper": bool(pick.get("keeper")),
        })

    season_started = False
    if detail.get("drafted"):
        try:
            season_started = _season_has_activity(league.espn_request.get_league())
        except Exception as error:
            print(f"Не удалось определить фактический старт сезона: {error}")
    if detail.get("inProgress"):
        status = "live"
    elif detail.get("drafted"):
        status = "completed"
    else:
        status = "upcoming"

    next_team_id = None
    raw_pick_order = settings.get("pickOrder") or []
    pick_order = _active_pick_order(raw)
    if status != "completed" and settings.get("type") == "SNAKE" and pick_order:
        next_index = len(picks)
        next_team_id = _snake_team_at(next_index, pick_order)
    if status == "live" and detail.get("liveSelectingTeamId"):
        next_team_id = detail["liveSelectingTeamId"]

    next_overall = len(picks) + 1 if status != "completed" else None
    next_round = ((next_overall - 1) // len(pick_order) + 1) if next_overall and pick_order else None
    next_round_pick = ((next_overall - 1) % len(pick_order) + 1) if next_overall and pick_order else None

    return {
        "status": status,
        "drafted": bool(detail.get("drafted")),
        "in_progress": bool(detail.get("inProgress")),
        "season_started": season_started,
        "postdraft": status == "completed" and not season_started,
        "phase": (
            "live_draft" if status == "live" else
            "draft_prep" if status == "upcoming" else
            "postdraft" if not season_started else
            "season"
        ),
        "pick_count": len(picks),
        "ignored_stale_picks": max(0, len(detail.get("picks", []) or []) - len(active_picks)),
        "live_source": bool(detail.get("liveSource")),
        "draft_connection_mode": detail.get("liveConnectionMode", "espn"),
        "live_snapshot_available": bool(detail.get("liveSnapshotAvailable")),
        "live_snapshot_frozen": bool(detail.get("liveSnapshotFrozen")),
        "live_sync_status": (
            "inactive" if status != "live" else
            "disabled" if detail.get("liveConnectionMode") == "espn" else
            "connected" if detail.get("liveSource") else
            "rest" if active_picks else
            "degraded" if detail.get("liveConnectionError") else
            "connecting"
        ),
        "live_updated_at": detail.get("liveUpdatedAt"),
        "live_connection_error": detail.get("liveConnectionError"),
        "picks": picks,
        "last_picks": list(reversed(picks[-12:])),
        "next_team_id": next_team_id,
        "next_team_name": team_names.get(next_team_id) if next_team_id else None,
        "next_overall": next_overall,
        "next_round": next_round,
        "next_round_pick": next_round_pick,
        "settings": {
            "type": settings.get("type"),
            "time_per_selection": settings.get("timePerSelection"),
            "auction_budget": settings.get("auctionBudget"),
            "pick_order": pick_order,
            "date": settings.get("date"),
            "order_known": bool(pick_order),
            "turn_projection_available": settings.get("type") == "SNAKE" and bool(pick_order),
            "ignored_stale_order": bool(raw_pick_order) and not bool(pick_order),
        },
        "team_count": len(team_names),
        "roster_size": draft_rounds,
        "draft_rounds": draft_rounds,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_draft_recommendations(
    league_metadata,
    team_id: int,
    period: str = PERIODS["projected"],
    punt_categories=(),
    limit: int = 25,
    mock_player_ids=(),
    simulation_slot=None,
):
    league = league_metadata.league
    market = get_espn_market(league_metadata)
    raw_draft = overlay_live_draft(league_metadata, league.espn_request.get_league_draft())
    active_picks = _active_picks(raw_draft)
    all_drafted_ids = list(dict.fromkeys(
        pick.get("playerId")
        for pick in active_picks
        if pick.get("playerId")
    ))
    drafted_id_set = {int(player_id) for player_id in all_drafted_ids}
    drafted_players = league.player_info(playerId=all_drafted_ids) if all_drafted_ids else []
    if drafted_players and not isinstance(drafted_players, list):
        drafted_players = [drafted_players]
    drafted_by_id = {getattr(player, "playerId", None): player for player in drafted_players or []}

    # ESPN's REST free-agent pool lags behind the Draft Lobby event stream and
    # may also contain the same player card more than once.  Live picks are the
    # source of truth for availability, so remove drafted IDs and duplicates
    # before scoring or simulating the remaining board.
    raw_free_agents = league_metadata.get_free_agents(size=300)
    free_agents = []
    seen_free_agents = set()
    for player in raw_free_agents:
        player_id = getattr(player, "playerId", None)
        normalized_id = int(player_id) if player_id is not None else None
        identity = ("id", normalized_id) if normalized_id is not None else ("name", player.name.casefold())
        if normalized_id in drafted_id_set or identity in seen_free_agents:
            continue
        seen_free_agents.add(identity)
        free_agents.append(player)
    current_stats = {
        int(player.playerId): stats
        for player in free_agents
        if getattr(player, "playerId", None) is not None
        if (stats := league_metadata.get_player_stats(player, period, "avg"))
    }
    use_previous_season = len(current_stats) < max(10, len(free_agents) // 2)
    previous_stats = _previous_season_stats(
        league_metadata,
        [getattr(player, "playerId", None) for player in free_agents]
        + all_drafted_ids,
    ) if use_previous_season else {}

    def stats_for(player):
        player_id = getattr(player, "playerId", None)
        if player_id is None:
            return None
        return previous_stats.get(int(player_id)) if use_previous_season else current_stats.get(int(player_id)) \
            or league_metadata.get_player_stats(player, period, "avg")

    score_population = []
    candidate_objects = {}
    candidate_objects_by_id = {}
    for player in free_agents:
        stats = stats_for(player)
        if not stats:
            continue
        score_population.append({
            "name": player.name,
            "position": getattr(player, "position", "N/A"),
            "team_id": 0,
            "team_name": "Available",
            "stats": stats,
        })
        candidate_objects[player.name] = player
        player_id = getattr(player, "playerId", None)
        if player_id is not None:
            candidate_objects_by_id[int(player_id)] = player
    for player in drafted_by_id.values():
        stats = stats_for(player)
        if stats:
            score_population.append({
                "name": player.name,
                "position": getattr(player, "position", "N/A"),
                "team_id": -1,
                "team_name": "Drafted",
                "stats": stats,
            })
    score_data = calculate_z_scores_from_players(score_population)
    scored = score_data["players"]
    scored_by_name = {player["name"]: player for player in scored}
    drafted_profiles_by_team = defaultdict(list)
    for pick in active_picks:
        player = drafted_by_id.get(pick.get("playerId"))
        scored_player = scored_by_name.get(getattr(player, "name", "")) if player else None
        if not player:
            continue
        player_stats = stats_for(player) or {}
        z_scores = scored_player.get("z_scores", {}) if scored_player else {}
        drafted_profiles_by_team[pick.get("teamId")].append({
            "name": player.name,
            "position": getattr(player, "position", "N/A"),
            "z_scores": z_scores,
            "general_z": sum(z_scores.values()),
            "score": sum(z_scores.values()),
            "games_played": int(player_stats.get("GP", 0) or 0),
        })

    # During a live draft the cached Team.roster may lag behind picks. Rebuild the
    # drafting roster from raw pick IDs in one player-card request instead.
    drafted_ids = [
        pick.get("playerId")
        for pick in active_picks
        if pick.get("teamId") == team_id and pick.get("playerId")
    ]
    roster = []
    if drafted_ids:
        roster = [drafted_by_id[player_id] for player_id in drafted_ids if player_id in drafted_by_id]
    if not roster:
        roster = list(league_metadata.get_team_roster(team_id) or [])
    actual_roster_ids = {getattr(player, "playerId", None) for player in roster}
    for player_id in mock_player_ids:
        player = candidate_objects_by_id.get(int(player_id))
        if player is not None and getattr(player, "playerId", None) not in actual_roster_ids:
            roster.append(player)
            actual_roster_ids.add(getattr(player, "playerId", None))
    position_counts = Counter(getattr(player, "position", "N/A") for player in roster)
    roster_names = {player.name for player in roster}
    roster_z = []
    roster_details = []
    team_pick_by_player = {
        int(pick["playerId"]): int(pick.get("overallPickNumber") or 0)
        for pick in active_picks
        if pick.get("teamId") == team_id and pick.get("playerId")
    }
    for roster_player in roster:
        stats = stats_for(roster_player) or {}
        player_z = calculate_player_z_scores(stats, score_data["league_metrics"]) if stats else {}
        if player_z:
            roster_z.append(player_z)
        player_id = getattr(roster_player, "playerId", None)
        roster_record = {
            "player_id": player_id,
            "name": roster_player.name,
            "position": getattr(roster_player, "position", "N/A"),
            "nba_team": getattr(roster_player, "proTeam", "N/A"),
            "total_z": round(sum(value for category, value in player_z.items() if category not in punt_categories), 3),
            "general_z": round(sum(player_z.values()), 3),
            "z_scores": player_z,
            "stats": stats,
            "games_played": int(stats.get("GP", 0) or 0),
            "analysis_context": "draft",
            "stats_source": f"сезон {league_metadata.year - 1}" if use_previous_season and previous_stats else f"сезон {league_metadata.year}",
            "stats_available": bool(stats),
        }
        attach_market(roster_record, market, player_id=player_id, name=roster_player.name)
        draft_pick = team_pick_by_player.get(int(player_id)) if player_id is not None else None
        roster_record["draft_pick"] = draft_pick
        roster_record["adp_value"] = round(draft_pick - roster_record["espn_adp"], 1) \
            if draft_pick and roster_record.get("espn_adp") is not None else None
        roster_details.append(roster_record)
    category_strength = {
        category: sum(player.get(category, 0) for player in roster_z)
        for category in CATEGORIES
        if category not in punt_categories
    }
    weakest = [
        category for category, _ in sorted(category_strength.items(), key=lambda item: item[1])[:3]
    ]

    team_count = max(1, len(league_metadata.get_teams()))
    draft_settings = raw_draft.get("settings", {}).get("draftSettings", {})
    draft_rounds = _draft_round_count(raw_draft, team_count)
    raw_pick_order = draft_settings.get("pickOrder") or []
    pick_order = _active_pick_order(raw_draft)
    next_pick_for_team = None
    picks_until_turn = None
    drafted_complete = bool(raw_draft.get("draftDetail", {}).get("drafted"))
    if not drafted_complete and draft_settings.get("type") == "SNAKE" and pick_order:
        current_pick_count = len(active_picks)
        for pick_index in range(current_pick_count, current_pick_count + len(pick_order) * 2):
            if _snake_team_at(pick_index, pick_order) == team_id:
                next_pick_for_team = pick_index + 1
                picks_until_turn = pick_index - current_pick_count
                break

    turn_projection_available = draft_settings.get("type") == "SNAKE" and bool(pick_order)
    planned_picks = _planned_team_picks(team_id, pick_order, rounds=draft_rounds) if turn_projection_available else []
    if raw_draft.get("draftDetail", {}).get("inProgress"):
        future_picks = [pick for pick in planned_picks if pick >= len(active_picks) + 1]
        planned_pick = future_picks[0] if future_picks else None
        following_pick = future_picks[1] if len(future_picks) > 1 else None
    else:
        planned_pick_index = min(len(mock_player_ids), max(0, len(planned_picks) - 1))
        planned_pick = planned_picks[planned_pick_index] if planned_picks else None
        following_pick = planned_picks[planned_pick_index + 1] if planned_picks and planned_pick_index + 1 < len(planned_picks) else None
    current_overall = len(active_picks) + 1
    is_on_the_clock = bool(
        not drafted_complete
        and turn_projection_available
        and picks_until_turn == 0
    )

    recommendations = []
    for player in scored:
        if player["name"] in roster_names or player["name"] not in candidate_objects:
            continue
        z_scores = player["z_scores"]
        total_z = sum(value for category, value in z_scores.items() if category not in punt_categories)
        general_z = sum(z_scores.values())
        source = candidate_objects[player["name"]]
        source_stats = stats_for(source)
        recommendation = {
            "player_id": getattr(source, "playerId", None),
            "name": player["name"],
            "position": player["position"],
            "nba_team": getattr(source, "proTeam", "N/A"),
            "injury_status": getattr(source, "injuryStatus", "ACTIVE"),
            "score": round(total_z, 3),
            "total_z": round(total_z, 3),
            "general_z": round(general_z, 3),
            "need_bonus": 0.0,
            "vorp": 0.0,
            "scarcity_bonus": 0.0,
            "z_scores": z_scores,
            "stats": source_stats,
            "games_played": int(source_stats.get("GP", 0) or 0) if source_stats else 0,
            "analysis_context": "draft",
            "stats_source": f"сезон {league_metadata.year - 1}" if use_previous_season and previous_stats else f"сезон {league_metadata.year}",
            "reason": "лучшая доступная ценность стратегии",
        }
        attach_market(
            recommendation,
            market,
            player_id=getattr(source, "playerId", None),
            name=player["name"],
        )
        recommendations.append(recommendation)

    annotate_availability(recommendations, planned_pick, following_pick, current_overall)
    opponent_rosters = [
        roster_players for drafted_team_id, roster_players in drafted_profiles_by_team.items()
        if drafted_team_id != team_id
    ]
    scoring_context = build_scoring_context(
        roster=roster_details,
        remaining=recommendations,
        eval_pick=planned_pick or current_overall,
        next_own_pick=following_pick,
        is_on_the_clock=is_on_the_clock,
        picks_until_turn=picks_until_turn,
        own_picks_left=max(1, draft_rounds - len(roster_details)),
        punt_categories=punt_categories,
        team_count=team_count,
        rounds=draft_rounds,
        opponent_rosters=opponent_rosters,
    )
    apply_pick_scores(recommendations, scoring_context)

    existing_rosters_by_slot = {}
    if pick_order:
        existing_rosters_by_slot = {
            index + 1: list(drafted_profiles_by_team.get(drafted_team_id, []))
            for index, drafted_team_id in enumerate(pick_order)
        }
    own_slot = pick_order.index(team_id) + 1 if pick_order and team_id in pick_order else None
    playoff_team_count = int(getattr(getattr(league, "settings", None), "playoff_team_count", 8) or 8)
    if is_on_the_clock and own_slot:
        recommendations = lookahead_rerank(
            recommendations,
            existing_rosters_by_slot=existing_rosters_by_slot or {own_slot: list(roster_details)},
            slot=own_slot,
            team_count=team_count,
            rounds=draft_rounds,
            current_pick=current_overall,
            punt_categories=punt_categories,
            playoff_team_count=playoff_team_count,
        )
    recommendations.sort(key=lambda player: player.get("score", 0), reverse=True)
    for board_rank, player in enumerate(recommendations, start=1):
        player["board_rank"] = board_rank
    pick_advice = build_pick_advice(recommendations, scoring_context)

    mock_id_set = {int(player_id) for player_id in mock_player_ids}
    mock_roster_profile = [
        {
            "name": player["name"],
            "position": player.get("position"),
            "z_scores": player.get("z_scores", {}),
            "general_z": player.get("general_z", 0),
            "score": player.get("total_z", 0),
            "games_played": player.get("games_played", 0),
        }
        for player in roster_details
        if player.get("player_id") in mock_id_set
    ]

    simulation = simulate_draft_market(
        recommendations,
        team_count=max(1, len(league_metadata.get_teams())),
        pick_order=pick_order,
        team_id=team_id,
        current_pick=current_overall,
        rounds=draft_rounds,
        selected_slot=simulation_slot,
        existing_rosters_by_slot=existing_rosters_by_slot,
        own_existing_roster=mock_roster_profile if mock_roster_profile and not active_picks else None,
        playoff_team_count=playoff_team_count,
        own_punt_categories=punt_categories,
    )

    team_names = _team_names(league_metadata)
    roster_comparison = _roster_comparison(drafted_profiles_by_team, team_names, team_id, punt_categories)
    round_balanced = _round_balanced_roster_comparison(
        drafted_profiles_by_team,
        team_names,
        team_id,
        len(active_picks),
        team_count,
        punt_categories,
    )
    postdraft_analysis = None
    if raw_draft.get("draftDetail", {}).get("drafted") and active_picks:
        profiles = {}
        for pick in active_picks:
            drafted_player = drafted_by_id.get(pick.get("playerId"))
            scored_player = scored_by_name.get(getattr(drafted_player, "name", "")) if drafted_player else None
            if not drafted_player:
                continue
            profile = profiles.setdefault(pick.get("teamId"), {category: 0.0 for category in CATEGORIES})
            for category, value in (scored_player.get("z_scores", {}) if scored_player else {}).items():
                profile[category] = profile.get(category, 0.0) + value
        power = []
        for profile_team_id, profile in profiles.items():
            score = sum(value for category, value in profile.items() if category not in punt_categories)
            power.append({
                "team_id": profile_team_id,
                "team_name": team_names.get(profile_team_id, f"Team {profile_team_id}"),
                "score": round(score, 2),
            })
        power.sort(key=lambda item: item["score"], reverse=True)
        projected_rank = next((index + 1 for index, item in enumerate(power) if item["team_id"] == team_id), None)
        main_profile = profiles.get(team_id, {})
        category_ranks = {}
        for category in CATEGORIES:
            ordered = sorted(profiles, key=lambda value: profiles[value].get(category, 0), reverse=True)
            category_ranks[category] = ordered.index(team_id) + 1 if team_id in ordered else None
        value_rows = [player for player in roster_details if player.get("adp_value") is not None]
        postdraft_analysis = {
            "projected_power_rank": projected_rank,
            "team_count": len(power),
            "power_score": next((item["score"] for item in power if item["team_id"] == team_id), None),
            "category_ranks": category_ranks,
            "strong_categories": sorted(main_profile, key=main_profile.get, reverse=True)[:4],
            "weak_categories": sorted(main_profile, key=main_profile.get)[:3],
            "average_adp_value": round(sum(item["adp_value"] for item in value_rows) / len(value_rows), 1) if value_rows else None,
            "best_value": max(value_rows, key=lambda item: item["adp_value"])["name"] if value_rows else None,
            "biggest_reach": min(value_rows, key=lambda item: item["adp_value"])["name"] if value_rows else None,
            "method": "draft_roster_z_power_rank",
            "comparison": roster_comparison,
        }

    roster_details.sort(key=lambda player: player["total_z"], reverse=True)
    return {
        "team_id": team_id,
        "period": period,
        "stats_source": "previous_season" if use_previous_season and previous_stats else "selected_period",
        "stats_season": league_metadata.year - 1 if use_previous_season and previous_stats else league_metadata.year,
        "analysis_context": "draft",
        "market_source": market.get("source"),
        "market_available": market.get("available", False),
        "market_stale": market.get("stale", False),
        "punt_categories": list(punt_categories),
        "weak_categories": weakest,
        "roster_size": len(roster),
        "roster_limit": draft_rounds,
        "draft_rounds": draft_rounds,
        "roster": roster_details,
        "position_counts": dict(position_counts),
        "category_strength": {category: round(value, 2) for category, value in category_strength.items()},
        "strategy_suggestions": _strategy_suggestions(category_strength, len(roster_z)),
        "mock_player_ids": [int(player_id) for player_id in mock_player_ids],
        "planned_picks": planned_picks,
        "planned_pick": planned_pick,
        "following_pick": following_pick,
        "order_known": bool(pick_order),
        "turn_projection_available": turn_projection_available,
        "ignored_stale_order": bool(raw_pick_order) and not bool(pick_order),
        "next_pick_for_team": next_pick_for_team,
        "picks_until_turn": picks_until_turn,
        "simulation": simulation,
        "roster_comparison": roster_comparison,
        "round_balanced_comparison": round_balanced,
        "postdraft_analysis": postdraft_analysis,
        "pick_advice": pick_advice,
        "method": "punt_aware_ev_lookahead",
        "players": recommendations[:limit],
    }
