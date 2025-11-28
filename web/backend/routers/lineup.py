"""
Роутер для оптимизации состава команды.
"""

from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
import sys
import os
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)
from utils.lineup_optimizer import optimize_lineup
from typing import List, Optional

router = APIRouter(prefix="/api/lineup", tags=["lineup"])


@router.get("/{team_id}/optimize")
def optimize_team_lineup(
    team_id: int,
    period: str = "2026_total",
    exclude_ir: bool = False,
    punt_categories: str = "",  # Список через запятую
    league_meta=Depends(get_league_meta)
):
    """
    Оптимизирует состав команды на основе матчапа.
    
    Args:
        team_id: ID команды
        period: Период статистики
        exclude_ir: Исключить IR игроков
        punt_categories: Список пант-категорий через запятую (например, "FT%,FG%")
    
    Returns:
        {
            'can_fit_all': bool,
            'start_lineup': {slot: player},
            'bench': [player],
            'analysis': {...}
        }
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем ростер
    roster = league_meta.get_team_roster(team_id)
    
    # Фильтруем игроков: исключаем IR и травмированных OUT
    available_players = []
    for player in roster:
        # Исключаем IR
        lineup_slot = getattr(player, 'lineupSlot', '')
        if lineup_slot == 'IR':
            continue
        
        # Исключаем травмированных OUT
        injury_status = getattr(player, 'injuryStatus', 'ACTIVE')
        is_injured = getattr(player, 'injured', False)
        if is_injured and injury_status == 'OUT':
            continue
        
        available_players.append(player)
    
    if not available_players:
        return {"error": "No available players"}
    
    # Получаем Z-scores для всех игроков
    z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    # Получаем статистику игроков команды
    team_players_data = []
    for player in available_players:
        player_name = player.name
        
        # Ищем игрока в данных Z-scores
        player_z_data = None
        for p in z_data['players']:
            if p['name'] == player_name:
                player_z_data = p
                break
        
        if not player_z_data:
            continue
        
        # Получаем eligibleSlots и position
        eligible_slots = getattr(player, 'eligibleSlots', [])
        position = getattr(player, 'position', '')
        
        team_players_data.append({
            'name': player_name,
            'position': position,
            'eligibleSlots': eligible_slots,
            'z_scores': player_z_data.get('z_scores', {})
        })
    
    # Получаем статистику команды и соперника
    current_week = league_meta.league.currentMatchupPeriod
    matchup_box = league_meta.get_matchup_box_score(current_week, team_id)
    
    if not matchup_box:
        return {"error": "No current matchup found"}
    
    opponent_id = matchup_box['opponent_id']
    
    # Получаем сводку матчапа
    matchup_summary = league_meta.get_matchup_summary(current_week, team_id, opponent_id)
    if not matchup_summary:
        return {"error": "Could not get matchup summary"}
    
    # Определяем статистику команды и соперника
    if matchup_summary['team1_id'] == team_id:
        team_stats = matchup_summary['team1_stats_filtered']
        opponent_stats = matchup_summary['team2_stats_filtered']
    else:
        team_stats = matchup_summary['team2_stats_filtered']
        opponent_stats = matchup_summary['team1_stats_filtered']
    
    # Парсим пант-категории
    punt_list = []
    if punt_categories:
        punt_list = [cat.strip() for cat in punt_categories.split(',') if cat.strip()]
    
    # Оптимизируем состав
    result = optimize_lineup(
        team_players_data,
        team_stats,
        opponent_stats,
        punt_list
    )
    
    # Добавляем информацию о матчапе
    result['matchup_info'] = {
        'opponent_name': matchup_box['opponent_name'],
        'opponent_id': opponent_id,
        'week': current_week
    }
    
    return result

