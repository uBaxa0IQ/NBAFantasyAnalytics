"""
Роутер для работы с балансом команд.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
import math

router = APIRouter(prefix="/api", tags=["balance"])


@router.get("/team-balance/{team_id}")
def get_team_balance(
    team_id: int,
    period: str = "2026_total",
    punt_categories: str = "",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """
    Получает данные для радар-графика баланса команды.
    Возвращает Z-scores по категориям.
    """
    # Парсим punt категории (для обратной совместимости, но не используем)
    # В дашборде всегда показываем все категории
    # punt_cats = []
    # if punt_categories:
    #     punt_cats = punt_categories.split(',')
    
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    if not team_players:
        return {"error": "Team not found"}
    
    # Получаем название команды
    team = league_meta.get_team_by_id(team_id)
    team_name = team.team_name if team else f"Team {team_id}"
    
    # Суммируем Z-scores по категориям (все категории, без исключений)
    category_totals = {cat: 0 for cat in CATEGORIES}
    
    for player in team_players:
        for cat in CATEGORIES:
            z_val = player['z_scores'].get(cat, 0)
            if math.isfinite(z_val):
                category_totals[cat] += z_val
    
    # Форматируем для Recharts (все категории)
    radar_data = []
    for cat in CATEGORIES:
        radar_data.append({
            'category': cat,
            'value': round(category_totals[cat], 2)
        })
    
    return {
        "team_id": team_id,
        "team_name": team_name,
        "period": period,
        "data": radar_data
    }

