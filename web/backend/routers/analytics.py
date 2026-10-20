"""
Роутер для аналитики команд.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import DEFAULT_PERIOD
import math

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics/{team_id}")
def get_analytics(
    team_id: int,
    period: str = DEFAULT_PERIOD,
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """Получает аналитику для команды."""
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    # Добавляем полную статистику к игрокам
    all_players_with_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    players_by_team_and_name = {
        (p['team_id'], p['name']): p for p in all_players_with_stats
    }
    
    # Добавляем статистику к каждому игроку
    for player in team_players:
        player_data = players_by_team_and_name.get((team_id, player['name']), {})
        player_stats = player_data.get('stats', {})
        player['is_ir'] = player_data.get('lineup_slot') == 'IR'
        # Очищаем stats от inf/nan
        clean_stats = {}
        if player_stats:
            for key, val in player_stats.items():
                if isinstance(val, float) and not math.isfinite(val):
                    clean_stats[key] = 0.0
                else:
                    clean_stats[key] = val
        player['stats'] = clean_stats
    
    return {
        "team_id": team_id,
        "period": period,
        "players": team_players,
        "league_metrics": data['league_metrics']
    }
