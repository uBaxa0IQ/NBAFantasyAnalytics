"""
Роутер для анализа плей-офф и сетки.
"""

from fastapi import APIRouter, Depends
from typing import List, Dict, Any, Optional

from dependencies import get_league_meta
from core.config import PLAYOFF_START_WEEK


router = APIRouter(prefix="/api/playoff", tags=["playoff"])


def _build_seeds(league_meta) -> List[Dict[str, Any]]:
    """
    Формирует список посевов (seeds) на основе текущих реальных результатов лиги.
    """
    teams = league_meta.get_teams()
    teams_with_records: List[Dict[str, Any]] = []

    for team in teams:
        wins = getattr(team, "wins", 0)
        losses = getattr(team, "losses", 0)
        ties = getattr(team, "ties", 0)
        total_games = wins + losses + ties
        win_pct = (wins + 0.5 * ties) / total_games if total_games > 0 else 0.0

        teams_with_records.append(
            {
                "team_id": team.team_id,
                "team_name": team.team_name,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_pct": win_pct,
            }
        )

    # Сортировка по винрейту и количеству побед (как в дашборде)
    teams_with_records.sort(key=lambda x: (x["win_pct"], x["wins"]), reverse=True)

    seeds: List[Dict[str, Any]] = []
    for idx, info in enumerate(teams_with_records, start=1):
        seeds.append(
            {
                "seed": idx,
                "team_id": info["team_id"],
                "team_name": info["team_name"],
                "wins": info["wins"],
                "losses": info["losses"],
                "ties": info["ties"],
                "win_pct": round(info["win_pct"] * 100, 1),
            }
        )

    return seeds


@router.get("/state")
def get_playoff_state(league_meta=Depends(get_league_meta)) -> Dict[str, Any]:
    """
    Возвращает базовую информацию о состоянии сезона:
    - текущая неделя
    - неделя начала плей-офф
    - флаг, что сейчас плей-офф
    """
    current_week = league_meta.league.currentMatchupPeriod
    is_playoff = current_week >= PLAYOFF_START_WEEK

    return {
        "current_week": current_week,
        "playoff_start_week": PLAYOFF_START_WEEK,
        "is_playoff": is_playoff,
    }


@router.get("/bracket")
def get_playoff_bracket(league_meta=Depends(get_league_meta)) -> Dict[str, Any]:
    """
    Возвращает «сетку» плей-офф для текущей недели:
    - посевы всех команд
    - список матчапов текущей недели с указанием посевов и (если есть данные) счёта.
    """
    current_week = league_meta.league.currentMatchupPeriod
    is_playoff = current_week >= PLAYOFF_START_WEEK

    seeds = _build_seeds(league_meta)
    id_to_seed = {s["team_id"]: s["seed"] for s in seeds}

    result: Dict[str, Any] = {
        "current_week": current_week,
        "playoff_start_week": PLAYOFF_START_WEEK,
        "is_playoff": is_playoff,
        "round": current_week - PLAYOFF_START_WEEK + 1 if is_playoff else None,
        "seeds": seeds,
        "matchups": [],
    }

    if not is_playoff:
        # В регулярке просто возвращаем посевы и базовую информацию
        return result

    # Матчапы текущей недели (включая утешительные)
    matchups_for_week = league_meta.get_matchups_for_week(current_week)

    for matchup in matchups_for_week:
        team1_id = matchup["team1_id"]
        team2_id = matchup["team2_id"]

        seed1: Optional[int] = id_to_seed.get(team1_id)
        seed2: Optional[int] = id_to_seed.get(team2_id)

        # Чемпионская сетка: хотя бы одна команда в топ‑8 по посеву
        max_seed = max(seed for seed in (seed1, seed2) if seed is not None) if (seed1 or seed2) else None
        bracket_type = "championship" if max_seed and max_seed <= 8 else "consolation"

        # Пытаемся получить сводку матчапа для счёта по категориям
        summary = league_meta.get_matchup_summary(current_week, team1_id, team2_id)
        if summary:
            score_info = {
                "team1_wins": summary["team1_wins"],
                "team2_wins": summary["team2_wins"],
                "ties": summary["ties"],
                "formatted": summary["score"],
            }
        else:
            score_info = None

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
                "score": score_info,
            }
        )

    return result

