"""
Роутер для дашборда команд.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
import math

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/{team_id}")
def get_dashboard(
    team_id: int,
    period: str = "2026_total",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """
    Получает данные для дашборда команды:
    - Информация о команде
    - Текущий матчап
    - Топ-3 игрока
    - Список травмированных игроков
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем ростер
    roster = league_meta.get_team_roster(team_id)
    
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    # Добавляем полную статистику к игрокам
    all_players_with_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    stats_by_name = {p['name']: p['stats'] for p in all_players_with_stats}
    
    for player in team_players:
        player['stats'] = stats_by_name.get(player['name'], {})
    
    # Вычисляем общий Z-score команды
    total_z_score = 0
    for player in team_players:
        player_z_total = sum(
            z for z in player['z_scores'].values() 
            if math.isfinite(z)
        )
        total_z_score += player_z_total
    
    # Топ-3 игрока по Z-score
    players_with_totals = []
    for player in team_players:
        total = sum(z for z in player['z_scores'].values() if math.isfinite(z))
        players_with_totals.append({
            'name': player['name'],
            'position': player['position'],
            'total_z': total,
            'z_scores': player['z_scores']
        })
    
    players_with_totals.sort(key=lambda x: x['total_z'], reverse=True)
    top_players = players_with_totals[:3]
    
    # Получаем текущую неделю
    current_week = league_meta.league.currentMatchupPeriod
    
    # Получаем текущий матчап
    current_matchup = None
    matchup_box = league_meta.get_matchup_box_score(current_week, team_id)
    if matchup_box:
        current_matchup = {
            'week': current_week,
            'opponent_name': matchup_box['opponent_name'],
            'opponent_id': matchup_box['opponent_id']
        }
    
    # Получаем список травмированных игроков
    injured_players = []
    for player in roster:
        injury_status = getattr(player, 'injuryStatus', 'ACTIVE')
        is_injured = getattr(player, 'injured', False)
        
        if is_injured or injury_status not in ['ACTIVE', None]:
            injured_players.append({
                'name': player.name,
                'position': getattr(player, 'position', 'N/A'),
                'injury_status': injury_status,
                'in_ir': getattr(player, 'lineupSlot', '') == 'IR'
            })
    
    return {
        "team_id": team_id,
        "team_name": team.team_name,
        "roster_size": len(roster),
        "total_z_score": round(total_z_score, 2),
        "current_matchup": current_matchup,
        "top_players": top_players,
        "injured_players": injured_players,
        "period": period
    }


@router.get("/{team_id}/matchup-details")
def get_matchup_details(
    team_id: int,
    week: int = None,
    league_meta=Depends(get_league_meta)
):
    """
    Получает детальную информацию о матчапе команды.
    Возвращает сравнение статистики по всем категориям.
    
    Args:
        team_id: ID команды
        week: Номер недели (если не указан, используется текущая неделя)
    """
    # Получаем текущую неделю или используем указанную
    if week is None:
        current_week = league_meta.league.currentMatchupPeriod
    else:
        current_week = week
    
    # Получаем текущий матчап
    matchup_box = league_meta.get_matchup_box_score(current_week, team_id)
    if not matchup_box:
        return {"error": "No current matchup found"}
    
    opponent_id = matchup_box['opponent_id']
    
    # Получаем детальную сводку матчапа
    matchup_summary = league_meta.get_matchup_summary(current_week, team_id, opponent_id)
    if not matchup_summary:
        return {"error": "Could not get matchup summary"}
    
    # Форматируем данные для фронтенда
    # Определяем, какая команда - team1, а какая - team2
    if matchup_summary['team1_id'] == team_id:
        my_team_stats = matchup_summary['team1_stats_filtered']
        opponent_stats = matchup_summary['team2_stats_filtered']
        my_team_name = matchup_summary['team1']
        opponent_name = matchup_summary['team2']
        my_wins = matchup_summary['team1_wins']
        opponent_wins = matchup_summary['team2_wins']
        ties = matchup_summary['ties']
    else:
        my_team_stats = matchup_summary['team2_stats_filtered']
        opponent_stats = matchup_summary['team1_stats_filtered']
        my_team_name = matchup_summary['team2']
        opponent_name = matchup_summary['team1']
        my_wins = matchup_summary['team2_wins']
        opponent_wins = matchup_summary['team1_wins']
        ties = matchup_summary['ties']
    
    # Формируем данные по категориям
    categories_data = []
    for cat in CATEGORIES:
        my_value = my_team_stats.get(cat, 0.0)
        opponent_value = opponent_stats.get(cat, 0.0)
        
        # Определяем победителя
        if my_value > opponent_value:
            winner = 'my_team'
        elif opponent_value > my_value:
            winner = 'opponent'
        else:
            winner = 'tie'
        
        categories_data.append({
            'category': cat,
            'my_value': my_value,
            'opponent_value': opponent_value,
            'winner': winner
        })
    
    return {
        'week': current_week,
        'my_team': {
            'id': team_id,
            'name': my_team_name,
            'wins': my_wins
        },
        'opponent': {
            'id': opponent_id,
            'name': opponent_name,
            'wins': opponent_wins
        },
        'score': f"{my_wins}-{opponent_wins}-{ties}",
        'categories': categories_data
    }


@router.get("/{team_id}/matchup-history")
def get_matchup_history(
    team_id: int,
    league_meta=Depends(get_league_meta)
):
    """
    Получает историю всех матчапов команды за все недели.
    Возвращает список матчапов с результатами.
    """
    # Получаем текущую неделю
    current_week = league_meta.league.currentMatchupPeriod
    
    # Собираем все матчапы команды (исключаем текущую неделю, так как она еще не завершена)
    matchup_history = []
    
    for week in range(1, current_week):
        matchup_box = league_meta.get_matchup_box_score(week, team_id)
        if not matchup_box:
            continue
        
        opponent_id = matchup_box['opponent_id']
        opponent_name = matchup_box['opponent_name']
        
        # Получаем сводку матчапа
        matchup_summary = league_meta.get_matchup_summary(week, team_id, opponent_id)
        if not matchup_summary:
            continue
        
        # Определяем, какая команда - team1, а какая - team2
        if matchup_summary['team1_id'] == team_id:
            my_wins = matchup_summary['team1_wins']
            opponent_wins = matchup_summary['team2_wins']
            ties = matchup_summary['ties']
            my_team_name = matchup_summary['team1']
        else:
            my_wins = matchup_summary['team2_wins']
            opponent_wins = matchup_summary['team1_wins']
            ties = matchup_summary['ties']
            my_team_name = matchup_summary['team2']
        
        # Определяем результат (W/L/T)
        if my_wins > opponent_wins:
            result = 'W'
        elif opponent_wins > my_wins:
            result = 'L'
        else:
            result = 'T'
        
        matchup_history.append({
            'week': week,
            'opponent_id': opponent_id,
            'opponent_name': opponent_name,
            'my_wins': my_wins,
            'opponent_wins': opponent_wins,
            'ties': ties,
            'score': f"{my_wins}-{opponent_wins}-{ties}",
            'result': result
        })
    
    # Сортируем по неделе (от новых к старым)
    matchup_history.sort(key=lambda x: x['week'], reverse=True)
    
    return {
        'team_id': team_id,
        'matchups': matchup_history
    }

