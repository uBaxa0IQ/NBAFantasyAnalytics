"""
Модуль для расчета Z-scores игроков.
Z-score показывает, на сколько стандартных отклонений игрок отличается от среднего по лиге.
"""

from typing import Dict, List, Any, Optional
import math
from .config import CATEGORIES, REVERSE_CATEGORIES



# Разделение категорий на счетные и процентные
COUNTING_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'TO']
PERCENTAGE_CATEGORIES = ['FG%', 'FT%', '3PT%', 'A/TO']


def calculate_player_z_scores(stats: Dict[str, Any], league_metrics: Dict[str, Any]) -> Dict[str, float]:
    """Score one player against metrics calculated from rostered league players."""
    z_scores = {}
    for category, metric in league_metrics.items():
        if 'mean' not in metric or category not in stats:
            continue
        value = (stats[category] - metric['mean']) / metric['std'] if metric['std'] else 0.0
        z_scores[category] = -value if metric.get('reverse') else value

    percentage_inputs = {
        'FG%': ('FG%', 'FGA'),
        'FT%': ('FT%', 'FTA'),
        '3PT%': ('3PT%', '3PA'),
    }
    for category, (percentage, attempts) in percentage_inputs.items():
        if percentage in stats and attempts in stats and category in league_metrics:
            metric = league_metrics[category]
            impact = (stats[percentage] - metric['weighted_avg']) * stats[attempts]
            z_scores[category] = (
                (impact - metric['impact_mean']) / metric['impact_std']
                if metric['impact_std'] else 0.0
            )

    if 'AST' in stats and 'TO' in stats and 'A/TO' in league_metrics:
        metric = league_metrics['A/TO']
        impact = stats['AST'] - stats['TO'] * metric['weighted_avg']
        z_scores['A/TO'] = (
            (impact - metric['impact_mean']) / metric['impact_std']
            if metric['impact_std'] else 0.0
        )
    return {
        category: value if math.isfinite(value) else 0.0
        for category, value in z_scores.items()
    }


def calculate_z_scores(league_metadata, period: str, exclude_ir: bool = False) -> Dict[str, Any]:
    all_players = league_metadata.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    return calculate_z_scores_from_players(
        all_players,
        categories=league_metadata.get_categories(),
        reverse_categories=league_metadata.reverse_categories,
    )


def calculate_z_scores_from_players(
    all_players: List[Dict[str, Any]],
    categories: Optional[List[str]] = None,
    reverse_categories=None,
) -> Dict[str, Any]:
    """
    Рассчитывает Z-scores для всех игроков лиги за указанный период.
    
    Args:
        league_metadata: Объект LeagueMetadata
        period: Период статистики (например, '2026_total', '2026_last_15')
        exclude_ir: Если True, исключает игроков в IR слоте из расчета
        
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
    if not all_players:
        return {'players': [], 'league_metrics': {}}
    
    categories = list(categories or CATEGORIES)
    reverse_categories = set(REVERSE_CATEGORIES if reverse_categories is None else reverse_categories)
    percentage_categories = [cat for cat in PERCENTAGE_CATEGORIES if cat in categories]
    counting_categories = [cat for cat in categories if cat not in percentage_categories]

    # Собираем данные для расчета метрик лиги
    counting_data = {cat: [] for cat in counting_categories}
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
        for cat in counting_categories:
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
    for cat in counting_categories:
        if counting_data[cat]:
            mean = sum(counting_data[cat]) / len(counting_data[cat])
            variance = sum((x - mean) ** 2 for x in counting_data[cat]) / len(counting_data[cat])
            std = math.sqrt(variance) if variance > 0 else 0.0001  # Избегаем деления на 0
            league_metrics[cat] = {
                'mean': mean,
                'std': std,
                'reverse': cat in reverse_categories,
            }
    
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
    impact_data = {cat: [] for cat in percentage_categories}
    
    for player in all_players:
        stats = player['stats']
        
        # FG% impact
        if 'FG%' in impact_data and 'FG%' in stats and 'FGA' in stats and 'FG%' in weighted_averages:
            fg_pct = stats['FG%']
            fga = stats['FGA']
            fg_avg = weighted_averages['FG%']
            impact = (fg_pct - fg_avg) * fga
            impact_data['FG%'].append(impact)
        
        # FT% impact
        if 'FT%' in impact_data and 'FT%' in stats and 'FTA' in stats and 'FT%' in weighted_averages:
            ft_pct = stats['FT%']
            fta = stats['FTA']
            ft_avg = weighted_averages['FT%']
            impact = (ft_pct - ft_avg) * fta
            impact_data['FT%'].append(impact)
        
        # 3PT% impact
        if '3PT%' in impact_data and '3PT%' in stats and '3PA' in stats and '3PT%' in weighted_averages:
            three_pct = stats['3PT%']
            three_pa = stats['3PA']
            three_avg = weighted_averages['3PT%']
            impact = (three_pct - three_avg) * three_pa
            impact_data['3PT%'].append(impact)
        
        # A/TO impact
        if 'A/TO' in impact_data and 'AST' in stats and 'TO' in stats and 'A/TO' in weighted_averages:
            ast = stats['AST']
            to = stats['TO']
            a_to_avg = weighted_averages['A/TO']
            impact = ast - to * a_to_avg
            impact_data['A/TO'].append(impact)
    
    # Рассчитываем метрики для процентных категорий (по impact)
    for cat in percentage_categories:
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
        z_scores = calculate_player_z_scores(stats, league_metrics)
        
        players_with_z_scores.append({
            'name': player['name'],
            'position': player['position'],
            'eligible_slots': list(player.get('eligible_slots') or ()),
            'team_id': player['team_id'],
            'team_name': player['team_name'],
            'z_scores': z_scores,
        })
    
    return {
        'players': players_with_z_scores,
        'league_metrics': league_metrics
    }
