"""
Роутер для работы с командами и лигой.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
import math

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


@router.get("/refresh-status")
def get_refresh_status(league_meta=Depends(get_league_meta)):
    """
    Получает информацию о последнем обновлении данных лиги.
    
    Returns:
        Словарь с информацией об обновлении:
        {
            "last_refresh_time": str (ISO формат) или null,
            "auto_refresh_enabled": bool
        }
    """
    last_refresh = league_meta.get_last_refresh_time()
    return {
        "last_refresh_time": last_refresh.isoformat() if last_refresh else None,
        "auto_refresh_enabled": True,
        "refresh_interval_minutes": 5
    }


# Старый эндпоинт /generate-prompt удален - теперь используется новый из routers/prompt.py

@router.get("/teams/{team_id}/players-for-selection")
def get_players_for_selection(
    team_id: int,
    period: str = "2026_total",
    league_meta=Depends(get_league_meta)
):
    """
    Получает список всех игроков команды (включая IR) с их Z-scores,
    отсортированных по total Z-score.
    
    Args:
        team_id: ID команды
        period: Период статистики
    
    Returns:
        Список игроков с их Z-scores, отсортированных по total Z-score
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем ростер команды (включая IR)
    roster = league_meta.get_team_roster(team_id)
    
    # Получаем Z-scores для всех игроков (включая IR)
    z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
    
    if not z_data['players']:
        return {"error": "No data found"}
    
    # Создаем словарь Z-scores по имени игрока
    z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
    
    # Формируем список игроков с их Z-scores
    players_list = []
    for player in roster:
        player_name = player.name
        z_scores = z_scores_by_name.get(player_name, {})
        
        # Рассчитываем total Z-score
        total_z = 0
        for cat, z_val in z_scores.items():
            if isinstance(z_val, (int, float)) and math.isfinite(z_val):
                total_z += z_val
        
        # Проверяем, находится ли игрок в IR
        lineup_slot = getattr(player, 'lineupSlot', '')
        is_ir = (lineup_slot == 'IR')
        
        players_list.append({
            'name': player_name,
            'position': getattr(player, 'position', 'N/A'),
            'z_scores': z_scores,
            'total_z': round(total_z, 2),
            'is_ir': is_ir
        })
    
    # Сортируем по total Z-score (по убыванию)
    players_list.sort(key=lambda x: x['total_z'], reverse=True)
    
    return {
        'team_id': team_id,
        'team_name': team.team_name,
        'players': players_list
    }
