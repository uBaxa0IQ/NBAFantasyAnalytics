"""
Роутер для работы с игроками.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores, COUNTING_CATEGORIES, PERCENTAGE_CATEGORIES
from core.config import CATEGORIES
import math

router = APIRouter(prefix="/api", tags=["players"])


@router.get("/free-agents")
def get_free_agents(
    period: str = "2026_total",
    position: str = None,
    league_meta=Depends(get_league_meta)
):
    """Получает список свободных агентов с их статистикой и Z-scores."""
    # Получаем свободных агентов
    free_agents = league_meta.get_free_agents(size=200, position=position)
    
    if not free_agents:
        return {"error": "No free agents found"}
    
    # Рассчитываем Z-scores для всех игроков лиги (чтобы получить метрики)
    data = calculate_z_scores(league_meta, period)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Собираем статистику свободных агентов
    fa_data = []
    for fa in free_agents:
        stats = league_meta.get_player_stats(fa, period, 'avg')
        if not stats:
            continue
        
        # Рассчитываем Z-scores для этого игрока
        z_scores = {}
        
        # Счетные категории
        for cat in COUNTING_CATEGORIES:
            if cat in stats and cat in data['league_metrics']:
                value = stats[cat]
                mean = data['league_metrics'][cat]['mean']
                std = data['league_metrics'][cat]['std']
                z_score = (value - mean) / std if std > 0 else 0
                # Проверка на inf/nan
                if not math.isfinite(z_score):
                    z_score = 0.0
                z_scores[cat] = z_score
        
        # Процентные категории
        if 'FG%' in stats and 'FGA' in stats and 'FG%' in data['league_metrics']:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = data['league_metrics']['FG%']['weighted_avg']
            impact = (fg_pct - fg_avg) * fga
            impact_mean = data['league_metrics']['FG%']['impact_mean']
            impact_std = data['league_metrics']['FG%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            if not math.isfinite(z_score):
                z_score = 0.0
            z_scores['FG%'] = z_score
        
        if 'FT%' in stats and 'FTA' in stats and 'FT%' in data['league_metrics']:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = data['league_metrics']['FT%']['weighted_avg']
            impact = (ft_pct - ft_avg) * fta
            impact_mean = data['league_metrics']['FT%']['impact_mean']
            impact_std = data['league_metrics']['FT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            if not math.isfinite(z_score):
                z_score = 0.0
            z_scores['FT%'] = z_score
        
        if '3PT%' in stats and '3PA' in stats and '3PT%' in data['league_metrics']:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = data['league_metrics']['3PT%']['weighted_avg']
            impact = (three_pct - three_avg) * three_pa
            impact_mean = data['league_metrics']['3PT%']['impact_mean']
            impact_std = data['league_metrics']['3PT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            if not math.isfinite(z_score):
                z_score = 0.0
            z_scores['3PT%'] = z_score
        
        if 'AST' in stats and 'TO' in stats and 'A/TO' in data['league_metrics']:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = data['league_metrics']['A/TO']['weighted_avg']
            impact = ast - to * a_to_avg
            impact_mean = data['league_metrics']['A/TO']['impact_mean']
            impact_std = data['league_metrics']['A/TO']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            if not math.isfinite(z_score):
                z_score = 0.0
            z_scores['A/TO'] = z_score
        
        # Проверяем все значения в stats на inf/nan
        clean_stats = {}
        for key, val in stats.items():
            if isinstance(val, float) and not math.isfinite(val):
                clean_stats[key] = 0.0
            else:
                clean_stats[key] = val
        
        fa_data.append({
            'name': fa.name,
            'position': getattr(fa, 'position', 'N/A'),
            'nba_team': getattr(fa, 'proTeam', 'N/A'),
            'z_scores': z_scores,
            'stats': clean_stats
        })
    
    return {
        "period": period,
        "position": position,
        "players": fa_data,
        "league_metrics": data['league_metrics']
    }


@router.get("/all-players")
def get_all_players(
    period: str = "2026_total",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """Получает список всех игроков лиги с их статистикой и Z-scores."""
    # Рассчитываем Z-scores для всех игроков лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Добавляем информацию о полной статистике к каждому игроку
    all_players_data = []
    for player in data['players']:
        # Получаем полную статистику игрока (не только Z-scores)
        # Находим команду игрока
        team = league_meta.get_team_by_id(player['team_id'])
        if team:
            roster = league_meta.get_team_roster(player['team_id'])
            # Находим игрока в ростере
            for roster_player in roster:
                if roster_player.name == player['name']:
                    stats = league_meta.get_player_stats(roster_player, period, 'avg')
                    
                    # Очищаем z_scores от inf/nan
                    clean_z_scores = {}
                    for cat, val in player['z_scores'].items():
                        if isinstance(val, (int, float)) and not math.isfinite(val):
                            clean_z_scores[cat] = 0.0
                        else:
                            clean_z_scores[cat] = val
                    
                    # Очищаем stats от inf/nan
                    clean_stats = {}
                    if stats:
                        for key, val in stats.items():
                            if isinstance(val, float) and not math.isfinite(val):
                                clean_stats[key] = 0.0
                            else:
                                clean_stats[key] = val
                    
                    all_players_data.append({
                        'name': player['name'],
                        'position': player['position'],
                        'nba_team': getattr(roster_player, 'proTeam', 'N/A'),
                        'fantasy_team': player['team_name'],
                        'fantasy_team_id': player['team_id'],
                        'z_scores': clean_z_scores,
                        'stats': clean_stats
                    })
                    break
    
    return {
        "period": period,
        "players": all_players_data,
        "league_metrics": data['league_metrics']
    }


@router.get("/player/{player_name}/trends")
def get_player_trends(
    player_name: str,
    league_meta=Depends(get_league_meta)
):
    """
    Получает тренды игрока на основе доступных периодов.
    Использует периоды: last_7, last_15, last_30, total для показа изменения статистики.
    """
    # Находим игрока во всех командах
    all_teams = league_meta.get_teams()
    player_obj = None
    player_team_id = None
    
    for team in all_teams:
        roster = league_meta.get_team_roster(team.team_id)
        for player in roster:
            if player.name == player_name:
                player_obj = player
                player_team_id = team.team_id
                break
        if player_obj:
            break
    
    # Если не найден в командах, ищем среди свободных агентов
    if not player_obj:
        free_agents = league_meta.get_free_agents(size=200)
        for fa in free_agents:
            if fa.name == player_name:
                player_obj = fa
                player_team_id = None  # Свободный агент не имеет team_id
                break
    
    if not player_obj:
        return {"error": "Player not found"}
    
    # Периоды для анализа (от короткого к длинному)
    periods = [
        {'key': '2026_last_7', 'label': 'Последние 7 дней', 'order': 1},
        {'key': '2026_last_15', 'label': 'Последние 15 дней', 'order': 2},
        {'key': '2026_last_30', 'label': 'Последние 30 дней', 'order': 3},
        {'key': '2026_total', 'label': 'Весь сезон', 'order': 4},
    ]
    
    trends = []
    
    for period_info in periods:
        period = period_info['key']
        
        # Получаем статистику игрока за период
        player_stats = league_meta.get_player_stats(player_obj, period, 'total')
        if not player_stats:
            continue
        
        # Фильтруем статистику по категориям
        filtered_stats = league_meta.filter_stats_by_categories(player_stats)
        
        # Рассчитываем Z-scores для всей лиги за этот период (только игроки в составах)
        period_z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
        league_metrics = period_z_data.get('league_metrics', {})
        
        # Находим Z-scores этого игрока
        player_z_scores = {}
        
        # Сначала пытаемся найти в списке игроков из calculate_z_scores (если игрок в составе)
        found_in_list = False
        for player_data in period_z_data.get('players', []):
            if player_data.get('name') == player_name:
                player_z_scores = player_data.get('z_scores', {})
                found_in_list = True
                break
        
        # Если не найден (свободный агент), рассчитываем Z-scores вручную относительно метрик лиги
        if not found_in_list and league_metrics:
            # Получаем avg статистику для расчета Z-scores
            player_stats_avg = league_meta.get_player_stats(player_obj, period, 'avg')
            if player_stats_avg:
                # Счетные категории
                for cat in COUNTING_CATEGORIES:
                    if cat in player_stats_avg and cat in league_metrics:
                        value = player_stats_avg[cat]
                        mean = league_metrics[cat]['mean']
                        std = league_metrics[cat]['std']
                        z_score = (value - mean) / std if std > 0 else 0
                        if math.isfinite(z_score):
                            player_z_scores[cat] = z_score
                
                # Процентные категории
                if 'FG%' in player_stats_avg and 'FGA' in player_stats_avg and 'FG%' in league_metrics:
                    fg_pct = player_stats_avg['FG%']
                    fga = player_stats_avg['FGA']
                    fg_avg = league_metrics['FG%']['weighted_avg']
                    impact = (fg_pct - fg_avg) * fga
                    impact_mean = league_metrics['FG%']['impact_mean']
                    impact_std = league_metrics['FG%']['impact_std']
                    z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                    if math.isfinite(z_score):
                        player_z_scores['FG%'] = z_score
                
                if 'FT%' in player_stats_avg and 'FTA' in player_stats_avg and 'FT%' in league_metrics:
                    ft_pct = player_stats_avg['FT%']
                    fta = player_stats_avg['FTA']
                    ft_avg = league_metrics['FT%']['weighted_avg']
                    impact = (ft_pct - ft_avg) * fta
                    impact_mean = league_metrics['FT%']['impact_mean']
                    impact_std = league_metrics['FT%']['impact_std']
                    z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                    if math.isfinite(z_score):
                        player_z_scores['FT%'] = z_score
                
                if '3PT%' in player_stats_avg and '3PA' in player_stats_avg and '3PT%' in league_metrics:
                    three_pct = player_stats_avg['3PT%']
                    three_pa = player_stats_avg['3PA']
                    three_avg = league_metrics['3PT%']['weighted_avg']
                    impact = (three_pct - three_avg) * three_pa
                    impact_mean = league_metrics['3PT%']['impact_mean']
                    impact_std = league_metrics['3PT%']['impact_std']
                    z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                    if math.isfinite(z_score):
                        player_z_scores['3PT%'] = z_score
                
                if 'AST' in player_stats_avg and 'TO' in player_stats_avg and 'A/TO' in league_metrics:
                    ast = player_stats_avg['AST']
                    to = player_stats_avg['TO']
                    a_to_avg = league_metrics['A/TO']['weighted_avg']
                    impact = ast - to * a_to_avg
                    impact_mean = league_metrics['A/TO']['impact_mean']
                    impact_std = league_metrics['A/TO']['impact_std']
                    z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                    if math.isfinite(z_score):
                        player_z_scores['A/TO'] = z_score
        
        # Вычисляем общий Z-score
        total_z = sum(z for z in player_z_scores.values() if math.isfinite(z))
        
        trends.append({
            'period': period_info['label'],
            'period_key': period,
            'order': period_info['order'],
            'stats': filtered_stats,
            'z_scores': player_z_scores,
            'total_z': round(total_z, 2)
        })
    
    # Сортируем по порядку (от короткого к длинному, "Весь сезон" - последний)
    trends.sort(key=lambda x: x['order'])
    
    # Убеждаемся, что "Весь сезон" действительно последний
    # Перемещаем его в конец, если он не там
    total_period = next((t for t in trends if t['period'] == 'Весь сезон'), None)
    if total_period:
        trends = [t for t in trends if t['period'] != 'Весь сезон'] + [total_period]
    
    return {
        'player_name': player_name,
        'trends': trends
    }


@router.get("/player/{player_name}/balance")
def get_player_balance(
    player_name: str,
    period: str = "2026_total",
    league_meta=Depends(get_league_meta)
):
    """
    Получает данные для радар-графика баланса игрока.
    Возвращает Z-scores по категориям.
    """
    # Находим игрока во всех командах или среди свободных агентов
    all_teams = league_meta.get_teams()
    player_obj = None
    player_team_id = None
    
    for team in all_teams:
        roster = league_meta.get_team_roster(team.team_id)
        for player in roster:
            if player.name == player_name:
                player_obj = player
                player_team_id = team.team_id
                break
        if player_obj:
            break
    
    # Если не найден в командах, ищем среди свободных агентов
    if not player_obj:
        free_agents = league_meta.get_free_agents(size=200)
        for fa in free_agents:
            if fa.name == player_name:
                player_obj = fa
                player_team_id = None
                break
    
    if not player_obj:
        return {"error": "Player not found"}
    
    # Рассчитываем Z-scores для всей лиги за этот период
    period_z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
    league_metrics = period_z_data.get('league_metrics', {})
    
    # Находим Z-scores этого игрока
    player_z_scores = {}
    
    # Сначала пытаемся найти в списке игроков из calculate_z_scores (если игрок в составе)
    found_in_list = False
    for player_data in period_z_data.get('players', []):
        if player_data.get('name') == player_name:
            player_z_scores = player_data.get('z_scores', {})
            found_in_list = True
            break
    
    # Если не найден (свободный агент), рассчитываем Z-scores вручную относительно метрик лиги
    if not found_in_list and league_metrics:
        # Получаем avg статистику для расчета Z-scores
        player_stats_avg = league_meta.get_player_stats(player_obj, period, 'avg')
        if player_stats_avg:
            # Счетные категории
            for cat in COUNTING_CATEGORIES:
                if cat in player_stats_avg and cat in league_metrics:
                    value = player_stats_avg[cat]
                    mean = league_metrics[cat]['mean']
                    std = league_metrics[cat]['std']
                    z_score = (value - mean) / std if std > 0 else 0
                    if math.isfinite(z_score):
                        player_z_scores[cat] = z_score
            
            # Процентные категории
            if 'FG%' in player_stats_avg and 'FGA' in player_stats_avg and 'FG%' in league_metrics:
                fg_pct = player_stats_avg['FG%']
                fga = player_stats_avg['FGA']
                fg_avg = league_metrics['FG%']['weighted_avg']
                impact = (fg_pct - fg_avg) * fga
                impact_mean = league_metrics['FG%']['impact_mean']
                impact_std = league_metrics['FG%']['impact_std']
                z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                if math.isfinite(z_score):
                    player_z_scores['FG%'] = z_score
            
            if 'FT%' in player_stats_avg and 'FTA' in player_stats_avg and 'FT%' in league_metrics:
                ft_pct = player_stats_avg['FT%']
                fta = player_stats_avg['FTA']
                ft_avg = league_metrics['FT%']['weighted_avg']
                impact = (ft_pct - ft_avg) * fta
                impact_mean = league_metrics['FT%']['impact_mean']
                impact_std = league_metrics['FT%']['impact_std']
                z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                if math.isfinite(z_score):
                    player_z_scores['FT%'] = z_score
            
            if '3PT%' in player_stats_avg and '3PA' in player_stats_avg and '3PT%' in league_metrics:
                three_pct = player_stats_avg['3PT%']
                three_pa = player_stats_avg['3PA']
                three_avg = league_metrics['3PT%']['weighted_avg']
                impact = (three_pct - three_avg) * three_pa
                impact_mean = league_metrics['3PT%']['impact_mean']
                impact_std = league_metrics['3PT%']['impact_std']
                z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                if math.isfinite(z_score):
                    player_z_scores['3PT%'] = z_score
            
            if 'AST' in player_stats_avg and 'TO' in player_stats_avg and 'A/TO' in league_metrics:
                ast = player_stats_avg['AST']
                to = player_stats_avg['TO']
                a_to_avg = league_metrics['A/TO']['weighted_avg']
                impact = ast - to * a_to_avg
                impact_mean = league_metrics['A/TO']['impact_mean']
                impact_std = league_metrics['A/TO']['impact_std']
                z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
                if math.isfinite(z_score):
                    player_z_scores['A/TO'] = z_score
    
    # Форматируем для Recharts
    radar_data = []
    for cat in CATEGORIES:
        z_val = player_z_scores.get(cat, 0)
        if not math.isfinite(z_val):
            z_val = 0
        radar_data.append({
            'category': cat,
            'value': round(z_val, 2)
        })
    
    return {
        "player_name": player_name,
        "period": period,
        "data": radar_data
    }

