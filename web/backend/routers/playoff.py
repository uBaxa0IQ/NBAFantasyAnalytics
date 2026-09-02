"""
Роутер для анализа плей-офф и сетки.
"""

from fastapi import APIRouter, Depends
from typing import Dict, Any

from dependencies import get_league_meta
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
def get_playoff_bracket(league_meta=Depends(get_league_meta)) -> Dict[str, Any]:
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

        result["matchups"].append(
            {
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
        )

    return result
