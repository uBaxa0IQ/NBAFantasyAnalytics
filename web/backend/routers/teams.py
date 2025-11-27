"""
Роутер для работы с командами и лигой.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta

router = APIRouter(prefix="/api", tags=["teams"])


@router.get("/teams")
def get_teams(league_meta=Depends(get_league_meta)):
    """Получает список всех команд лиги."""
    teams = league_meta.get_teams()
    return [{"team_id": t.team_id, "team_name": t.team_name} for t in teams]


@router.post("/refresh-league")
def refresh_league(league_meta=Depends(get_league_meta)):
    """
    Обновляет данные лиги из ESPN API.
    Перезагружает информацию о командах, игроках и их статусах (включая травмы).
    
    Returns:
        Словарь с результатом обновления:
        {
            "success": bool,
            "message": str
        }
    """
    try:
        success = league_meta.refresh_league()
        if success:
            return {
                "success": True,
                "message": "Данные лиги успешно обновлены"
            }
        else:
            return {
                "success": False,
                "message": "Ошибка при обновлении данных лиги"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Ошибка при обновлении данных: {str(e)}"
        }


@router.get("/weeks")
def get_weeks(league_meta=Depends(get_league_meta)):
    """Получает список всех недель и текущую неделю."""
    weeks = list(range(1, league_meta.league.currentMatchupPeriod + 1))
    return {
        "weeks": weeks,
        "current_week": league_meta.league.currentMatchupPeriod
    }

