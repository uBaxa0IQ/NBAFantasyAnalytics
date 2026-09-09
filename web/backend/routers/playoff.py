"""
Роутер для анализа плей-офф и сетки.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any
from itertools import combinations
from time import monotonic

from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD
from core.playoff import (
    advance_title_contenders,
    build_seeds,
    get_matchup_bracket_type,
    get_playoff_context,
)


router = APIRouter(prefix="/api/playoff", tags=["playoff"])


@router.get("/state")
def get_playoff_state(league_meta=Depends(get_league_meta)) -> Dict[str, Any]:
    return get_playoff_context(league_meta.league)


@router.get("/bracket")
def get_playoff_bracket(
    period: str = DEFAULT_PERIOD,
    calculation_engine: str = "calendar",
    league_meta=Depends(get_league_meta),
) -> Dict[str, Any]:
    """
    Возвращает «сетку» плей-офф для текущей недели:
    - посевы всех команд
    - список матчапов текущей недели с указанием посевов и (если есть данные) счёта.
    """
    context = get_playoff_context(league_meta.league)
    current_week = context["current_week"]
    seeds = build_seeds(league_meta.get_teams())
    id_to_seed = {s["team_id"]: s["seed"] for s in seeds}

    result: Dict[str, Any] = {
        **context,
        "seeds": seeds,
        "matchups": [],
    }

    if not context["is_playoff_period"]:
        # В регулярке просто возвращаем посевы и базовую информацию
        return result

    # Матчапы текущей недели (включая утешительные)
    title_contenders = {
        seed["team_id"]
        for seed in seeds
        if seed["seed"] is not None and seed["seed"] <= context["playoff_team_count"]
    }
    for period in context["playoff_periods"]:
        if period >= current_week:
            break
        title_contenders = advance_title_contenders(
            title_contenders,
            league_meta.get_matchups_with_scores(period),
        )

    matchups_for_week = league_meta.get_matchups_with_scores(current_week)

    engine_inputs = None
    if calculation_engine == "probabilistic" and league_meta.scoring_type == "H2H_MOST_CATEGORIES":
        from services.matchup_engine import build_engine_inputs
        engine_inputs = build_engine_inputs(league_meta, period)

    for matchup in matchups_for_week:
        team1_id = matchup["team1_id"]
        team2_id = matchup["team2_id"]

        seed1 = id_to_seed.get(team1_id)
        seed2 = id_to_seed.get(team2_id)
        bracket_type = get_matchup_bracket_type(
            team1_id,
            team2_id,
            seed1,
            seed2,
            context["playoff_team_count"],
            title_contenders,
        )

        row = {
                "week": current_week,
                "type": bracket_type,
                "team1": {
                    "id": team1_id,
                    "name": matchup["team1"],
                    "seed": seed1,
                },
                "team2": {
                    "id": team2_id,
                    "name": matchup["team2"],
                    "seed": seed2,
                },
                "score": matchup["score"],
                "winner": matchup["winner"],
            }
        if engine_inputs is not None:
            from services.matchup_engine import simulate_pair
            odds = simulate_pair(league_meta, engine_inputs, team1_id, team2_id, current_week, remaining_only=True, trials=500)
            row["p_team1_win"] = odds["p_win"]
            row["p_tie"] = odds["p_tie"]
            row["p_team2_win"] = odds["p_loss"]
            row["flippable"] = odds["flippable"]
            row["trials"] = odds["trials"]
        result["matchups"].append(row)

    if engine_inputs is not None:
        advances = {}
        for row in result["matchups"]:
            if row.get("type") == "championship":
                advances[str(row["team1"]["id"])] = row.get("p_team1_win")
                advances[str(row["team2"]["id"])] = row.get("p_team2_win")
        cache = getattr(league_meta, "_playoff_title_cache", {})
        cache_key = (current_week, period, str(league_meta.last_refresh_time), tuple(sorted(title_contenders)))
        cached = cache.get(cache_key)
        if cached and monotonic() - cached[0] < 300:
            title_odds = cached[1]
        else:
            from core.matchup_mc import stable_seed
            from core.season_mc import simulate_playoff_title
            pair_probabilities = {}
            seed_by_team = {row["team_id"]: row["seed"] for row in seeds}
            for left, right in combinations(sorted(title_contenders), 2):
                odds = simulate_pair(league_meta, engine_inputs, left, right, current_week, remaining_only=False, trials=100)
                tie_to_left = (seed_by_team.get(left) or 999) < (seed_by_team.get(right) or 999)
                left_advance = odds["p_win"] + (odds["p_tie"] if tie_to_left else 0.0)
                pair_probabilities[(left, right)] = left_advance
                pair_probabilities[(right, left)] = 1.0 - left_advance
            contender_seeds = [row for row in seeds if row["team_id"] in title_contenders]
            title_odds = simulate_playoff_title(
                contender_seeds, pair_probabilities, trials=1200,
                seed=stable_seed(league_meta.league_id, league_meta.year, current_week, "playoff-title-v1"),
            )
            if len(cache) > 8:
                cache.clear()
            cache[cache_key] = (monotonic(), title_odds)
            league_meta._playoff_title_cache = cache
        result["title_odds"] = {str(team_id): probability for team_id, probability in title_odds.items()}
        result["probabilistic_note"] = "Шанс титула моделирует стандартную фиксированную сетку; ничья отдаётся команде с более высоким посевом."

    return result
