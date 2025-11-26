"""
Модуль для расчета Z-scores игроков.
Z-score показывает, на сколько стандартных отклонений игрок отличается от среднего по лиге.
"""

from typing import Dict, List, Any, Optional
import math
from .config import CATEGORIES



# Разделение категорий на счетные и процентные
COUNTING_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD']
PERCENTAGE_CATEGORIES = ['FG%', 'FT%', '3PT%', 'A/TO']


def calculate_z_scores(league_metadata, period: str) -> Dict[str, Any]:
    """
    Рассчитывает Z-scores для всех игроков лиги за указанный период.
    
    Args:
        league_metadata: Объект LeagueMetadata
        period: Период статистики (например, '2026_total', '2026_last_15')
        
    Returns:
        Словарь с Z-scores игроков и метриками лиги:
        {
            'players': [
                {
                    'name': str,
                    'team_id': int,
                    'team_name': str,
                    'z_scores': {category: z_score}
                }
            ],
            'league_metrics': {
                'PTS': {'mean': float, 'std': float},
                'FG%': {'weighted_avg': float, 'impact_mean': float, 'impact_std': float},
                ...
            }
        }
    """
    # Получаем avg статистику всех игроков
    all_players = league_metadata.get_all_players_stats(period, 'avg')
    
    if not all_players:
        return {'players': [], 'league_metrics': {}}
    
    # Собираем данные для расчета метрик лиги
    counting_data = {cat: [] for cat in COUNTING_CATEGORIES}
    percentage_data = {
        'FG%': {'FGM': [], 'FGA': []},
        'FT%': {'FTM': [], 'FTA': []},
        '3PT%': {'3PM': [], '3PA': []},
        'A/TO': {'AST': [], 'TO': []}
    }
    
    # Собираем данные по игрокам
    for player in all_players:
        stats = player['stats']
        
        # Счетные категории
        for cat in COUNTING_CATEGORIES:
            if cat in stats:
                counting_data[cat].append(stats[cat])
        
        # Процентные категории - собираем исходные данные
        if 'FGM' in stats and 'FGA' in stats:
            percentage_data['FG%']['FGM'].append(stats['FGM'])
            percentage_data['FG%']['FGA'].append(stats['FGA'])
        
        if 'FTM' in stats and 'FTA' in stats:
            percentage_data['FT%']['FTM'].append(stats['FTM'])
            percentage_data['FT%']['FTA'].append(stats['FTA'])
        
        if '3PM' in stats and '3PA' in stats:
            percentage_data['3PT%']['3PM'].append(stats['3PM'])
            percentage_data['3PT%']['3PA'].append(stats['3PA'])
        
        if 'AST' in stats and 'TO' in stats:
            percentage_data['A/TO']['AST'].append(stats['AST'])
            percentage_data['A/TO']['TO'].append(stats['TO'])
    
    # Рассчитываем метрики лиги для счетных категорий
    league_metrics = {}
    for cat in COUNTING_CATEGORIES:
        if counting_data[cat]:
            mean = sum(counting_data[cat]) / len(counting_data[cat])
            variance = sum((x - mean) ** 2 for x in counting_data[cat]) / len(counting_data[cat])
            std = math.sqrt(variance) if variance > 0 else 0.0001  # Избегаем деления на 0
            league_metrics[cat] = {'mean': mean, 'std': std}
    
    # Рассчитываем weighted averages для процентных категорий
    weighted_averages = {}
    
    # FG%
    if percentage_data['FG%']['FGM'] and percentage_data['FG%']['FGA']:
        total_fgm = sum(percentage_data['FG%']['FGM'])
        total_fga = sum(percentage_data['FG%']['FGA'])
        weighted_averages['FG%'] = total_fgm / total_fga if total_fga > 0 else 0
    
    # FT%
    if percentage_data['FT%']['FTM'] and percentage_data['FT%']['FTA']:
        total_ftm = sum(percentage_data['FT%']['FTM'])
        total_fta = sum(percentage_data['FT%']['FTA'])
        weighted_averages['FT%'] = total_ftm / total_fta if total_fta > 0 else 0
    
    # 3PT%
    if percentage_data['3PT%']['3PM'] and percentage_data['3PT%']['3PA']:
        total_3pm = sum(percentage_data['3PT%']['3PM'])
        total_3pa = sum(percentage_data['3PT%']['3PA'])
        weighted_averages['3PT%'] = total_3pm / total_3pa if total_3pa > 0 else 0
    
    # A/TO
    if percentage_data['A/TO']['AST'] and percentage_data['A/TO']['TO']:
        total_ast = sum(percentage_data['A/TO']['AST'])
        total_to = sum(percentage_data['A/TO']['TO'])
        weighted_averages['A/TO'] = total_ast / total_to if total_to > 0 else 0
    
    # Рассчитываем impact для процентных категорий
    impact_data = {cat: [] for cat in PERCENTAGE_CATEGORIES}
    
    for player in all_players:
        stats = player['stats']
        
        # FG% impact
        if 'FG%' in stats and 'FGA' in stats and 'FG%' in weighted_averages:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = weighted_averages['FG%']
            impact = (fg_pct - fg_avg) * fga
            impact_data['FG%'].append(impact)
        
        # FT% impact
        if 'FT%' in stats and 'FTA' in stats and 'FT%' in weighted_averages:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = weighted_averages['FT%']
            impact = (ft_pct - ft_avg) * fta
            impact_data['FT%'].append(impact)
        
        # 3PT% impact
        if '3PT%' in stats and '3PA' in stats and '3PT%' in weighted_averages:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = weighted_averages['3PT%']
            impact = (three_pct - three_avg) * three_pa
            impact_data['3PT%'].append(impact)
        
        # A/TO impact
        if 'AST' in stats and 'TO' in stats and 'A/TO' in weighted_averages:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = weighted_averages['A/TO']
            impact = ast - to * a_to_avg
            impact_data['A/TO'].append(impact)
    
    # Рассчитываем метрики для процентных категорий (по impact)
    for cat in PERCENTAGE_CATEGORIES:
        if impact_data[cat]:
            impact_mean = sum(impact_data[cat]) / len(impact_data[cat])
            variance = sum((x - impact_mean) ** 2 for x in impact_data[cat]) / len(impact_data[cat])
            impact_std = math.sqrt(variance) if variance > 0 else 0.0001
            league_metrics[cat] = {
                'weighted_avg': weighted_averages.get(cat, 0),
                'impact_mean': impact_mean,
                'impact_std': impact_std
            }
    
    # Рассчитываем Z-scores для всех игроков
    players_with_z_scores = []
    
    for player in all_players:
        stats = player['stats']
        z_scores = {}
        
        # Z-scores для счетных категорий
        for cat in COUNTING_CATEGORIES:
            if cat in stats and cat in league_metrics:
                value = stats[cat]
                mean = league_metrics[cat]['mean']
                std = league_metrics[cat]['std']
                z_score = (value - mean) / std if std > 0 else 0
                z_scores[cat] = max(0, z_score)  # Обрезаем отрицательные значения
        
        # Z-scores для процентных категорий (через impact)
        # Для процентных категорий НЕ обрезаем отрицательные значения
        # FG%
        if 'FG%' in stats and 'FGA' in stats and 'FG%' in league_metrics:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = league_metrics['FG%']['weighted_avg']
            impact = (fg_pct - fg_avg) * fga
            impact_mean = league_metrics['FG%']['impact_mean']
            impact_std = league_metrics['FG%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['FG%'] = z_score  # Оставляем отрицательные значения
        
        # FT%
        if 'FT%' in stats and 'FTA' in stats and 'FT%' in league_metrics:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = league_metrics['FT%']['weighted_avg']
            impact = (ft_pct - ft_avg) * fta
            impact_mean = league_metrics['FT%']['impact_mean']
            impact_std = league_metrics['FT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['FT%'] = z_score  # Оставляем отрицательные значения
        
        # 3PT%
        if '3PT%' in stats and '3PA' in stats and '3PT%' in league_metrics:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = league_metrics['3PT%']['weighted_avg']
            impact = (three_pct - three_avg) * three_pa
            impact_mean = league_metrics['3PT%']['impact_mean']
            impact_std = league_metrics['3PT%']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['3PT%'] = z_score  # Оставляем отрицательные значения
        
        # A/TO
        if 'AST' in stats and 'TO' in stats and 'A/TO' in league_metrics:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = league_metrics['A/TO']['weighted_avg']
            impact = ast - to * a_to_avg
            impact_mean = league_metrics['A/TO']['impact_mean']
            impact_std = league_metrics['A/TO']['impact_std']
            z_score = (impact - impact_mean) / impact_std if impact_std > 0 else 0
            z_scores['A/TO'] = z_score  # Оставляем отрицательные значения
        
        players_with_z_scores.append({
            'name': player['name'],
            'position': player['position'],
            'team_id': player['team_id'],
            'team_name': player['team_name'],
            'z_scores': z_scores
        })
    
    return {
        'players': players_with_z_scores,
        'league_metrics': league_metrics
    }

