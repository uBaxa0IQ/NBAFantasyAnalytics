"""
Роутер для работы с балансом команд.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
from utils.calculations import select_top_n_players
from typing import Optional, List
import math

router = APIRouter(prefix="/api", tags=["balance"])


@router.get("/team-balance/{team_id}")
def get_team_balance(
    team_id: int,
    period: str = "2026_total",
    punt_categories: str = "",
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_players: Optional[str] = None,
    league_meta=Depends(get_league_meta)
):
    """
    Получает данные для радар-графика баланса команды.
    Возвращает Z-scores по категориям.
    """
    # Определяем exclude_ir на основе simulation_mode
    exclude_ir = (simulation_mode == "exclude_ir")
    
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    # Если режим "top_n", применяем логику выбора топ-N игроков
    if simulation_mode == "top_n":
        # Парсим custom_team_players из строки в список
        custom_players_list = None
        if custom_team_players:
            custom_players_list = [name.strip() for name in custom_team_players.split(',') if name.strip()]
        
        z_scores_by_name = {p['name']: p['z_scores'] for p in data['players']}
        
        # Для custom_team_players используем выбранных игроков или топ-N
        if custom_players_list:
            # Фильтруем только выбранных игроков
            team_players = [p for p in team_players if p['name'] in custom_players_list]
        else:
            # Выбираем топ-N игроков
            team_players = select_top_n_players(
                team_players, 
                top_n_players, 
                punt_categories=[], 
                z_scores_data=z_scores_by_name
            )
    
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

