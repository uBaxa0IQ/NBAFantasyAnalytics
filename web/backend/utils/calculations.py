"""
Общие функции для расчетов статистики.
"""
import math
from core.config import CATEGORIES


def calculate_total_z(players, punt_cats):
    """
    Рассчитывает общий Z-score для списка игроков.
    
    Args:
        players: Список игроков с z_scores
        punt_cats: Список категорий для исключения (punt)
    
    Returns:
        float: Общий Z-score
    """
    total = 0
    for player in players:
        for cat in CATEGORIES:
            if cat not in punt_cats:
                z_val = player['z_scores'].get(cat, 0)
                if math.isfinite(z_val):
                    total += z_val
    return total


def calculate_category_z(players, punt_cats):
    """
    Рассчитывает Z-scores по категориям для списка игроков.
    
    Args:
        players: Список игроков с z_scores
        punt_cats: Список категорий для исключения (punt)
    
    Returns:
        dict: Словарь {category: total_z_score}
    """
    cat_totals = {cat: 0 for cat in CATEGORIES}
    for player in players:
        for cat in CATEGORIES:
            if cat not in punt_cats:
                z_val = player['z_scores'].get(cat, 0)
                if math.isfinite(z_val):
                    cat_totals[cat] += z_val
    return cat_totals


def calculate_raw_stats(players, punt_cats):
    """
    Рассчитывает реальные значения статистики (raw stats) с взвешенными процентами.
    
    Args:
        players: Список игроков со stats
        punt_cats: Список категорий для исключения (punt)
    
    Returns:
        dict: Словарь со статистикой по категориям
    """
    # Для процентных категорий собираем попадания и попытки
    counting_stats = {cat: 0 for cat in ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'TO']}
    fg_makes = 0
    fg_attempts = 0
    ft_makes = 0
    ft_attempts = 0
    three_makes = 0
    three_attempts = 0
    assists = 0
    turnovers = 0
    
    for player in players:
        # Получаем stats игрока - они уже есть в player dictionary  
        stats = player.get('stats', {})
        
        # Счетные категории
        for cat in counting_stats:
            if cat not in punt_cats:
                val = stats.get(cat, 0)
                counting_stats[cat] += val if math.isfinite(val) else 0
        
        # Для процентов собираем попадания и попытки
        if 'FG%' not in punt_cats:
            fgm = stats.get('FGM', 0)
            fga = stats.get('FGA', 0)
            fg_makes += fgm if math.isfinite(fgm) else 0
            fg_attempts += fga if math.isfinite(fga) else 0
        
        if 'FT%' not in punt_cats:
            ftm = stats.get('FTM', 0)
            fta = stats.get('FTA', 0)
            ft_makes += ftm if math.isfinite(ftm) else 0
            ft_attempts += fta if math.isfinite(fta) else 0
        
        if '3PT%' not in punt_cats:
            tpm = stats.get('3PM', 0)
            tpa = stats.get('3PA', 0)
            three_makes += tpm if math.isfinite(tpm) else 0
            three_attempts += tpa if math.isfinite(tpa) else 0
        
        if 'A/TO' not in punt_cats:
            ast = stats.get('AST', 0)
            to = stats.get('TO', 0)
            assists += ast if math.isfinite(ast) else 0
            turnovers += to if math.isfinite(to) else 0
    
    # Рассчитываем взвешенные проценты
    raw_stats = counting_stats.copy()
    
    if 'FG%' not in punt_cats:
        raw_stats['FG%'] = (fg_makes / fg_attempts * 100) if fg_attempts > 0 else 0
    
    if 'FT%' not in punt_cats:
        raw_stats['FT%'] = (ft_makes / ft_attempts * 100) if ft_attempts > 0 else 0
    
    if '3PT%' not in punt_cats:
        raw_stats['3PT%'] = (three_makes / three_attempts * 100) if three_attempts > 0 else 0
    
    if 'A/TO' not in punt_cats:
        raw_stats['A/TO'] = (assists / turnovers) if turnovers > 0 else (assists if assists > 0 else 0)
    
    return raw_stats


def calculate_team_category_z(team_players):
    """
    Рассчитывает Z-scores по категориям для команды.
    
    Args:
        team_players: Список игроков команды с z_scores
    
    Returns:
        dict: Словарь {category: total_z_score}
    """
    cat_totals = {cat: 0 for cat in CATEGORIES}
    for player in team_players:
        for cat in CATEGORIES:
            z_val = player['z_scores'].get(cat, 0)
            if math.isfinite(z_val):
                cat_totals[cat] += z_val
    return cat_totals


def calculate_team_raw_stats(team_players):
    """
    Рассчитывает статистику команды (raw stats) с взвешенными процентами.
    
    Args:
        team_players: Список игроков команды со stats
    
    Returns:
        dict: Словарь со статистикой по категориям
    """
    counting_stats = {cat: 0 for cat in ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'TO']}
    fg_makes = 0
    fg_attempts = 0
    ft_makes = 0
    ft_attempts = 0
    three_makes = 0
    three_attempts = 0
    assists = 0
    turnovers = 0
    
    for player in team_players:
        stats = player.get('stats', {})
        
        # Счетные категории
        for cat in counting_stats:
            val = stats.get(cat, 0)
            counting_stats[cat] += val if math.isfinite(val) else 0
        
        # Для процентов собираем попадания и попытки
        fgm = stats.get('FGM', 0)
        fga = stats.get('FGA', 0)
        fg_makes += fgm if math.isfinite(fgm) else 0
        fg_attempts += fga if math.isfinite(fga) else 0
        
        ftm = stats.get('FTM', 0)
        fta = stats.get('FTA', 0)
        ft_makes += ftm if math.isfinite(ftm) else 0
        ft_attempts += fta if math.isfinite(fta) else 0
        
        tpm = stats.get('3PM', 0)
        tpa = stats.get('3PA', 0)
        three_makes += tpm if math.isfinite(tpm) else 0
        three_attempts += tpa if math.isfinite(tpa) else 0
        
        ast = stats.get('AST', 0)
        to = stats.get('TO', 0)
        assists += ast if math.isfinite(ast) else 0
        turnovers += to if math.isfinite(to) else 0
    
    # Рассчитываем взвешенные проценты
    raw_stats = counting_stats.copy()
    
    raw_stats['FG%'] = (fg_makes / fg_attempts * 100) if fg_attempts > 0 else 0
    raw_stats['FT%'] = (ft_makes / ft_attempts * 100) if ft_attempts > 0 else 0
    raw_stats['3PT%'] = (three_makes / three_attempts * 100) if three_attempts > 0 else 0
    raw_stats['A/TO'] = (assists / turnovers) if turnovers > 0 else (assists if assists > 0 else 0)
    
    return raw_stats


def calculate_simulation_ranks(all_players_list, mode_type, league_meta, period, exclude_ir, punt_categories):
    """
    Рассчитывает симуляцию для всех команд и возвращает места в рейтинге.
    Использует тот же метод, что и /api/simulation - симуляцию "все против всех".
    
    Args:
        all_players_list: Список всех игроков лиги (с учетом или без учета трейда)
        mode_type: 'z_scores' или 'team_stats_avg'
        league_meta: Экземпляр LeagueMetadata
        period: Период для расчета
        exclude_ir: Исключать ли игроков на IR
        punt_categories: Список категорий для исключения (punt)
    
    Returns:
        dict: Словарь {team_id: rank} где rank - место в рейтинге (1 = первое место)
    """
    from core.z_score import calculate_z_scores
    
    # Получаем все команды
    teams = league_meta.get_teams()
    team_stats = {}
    
    if mode_type == 'z_scores':
        # Режим по Z-score
        # Группируем игроков по командам
        players_by_team = {}
        for player in all_players_list:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
        # Рассчитываем Z-scores для каждой команды
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                cat_totals = {cat: 0 for cat in CATEGORIES}
                for player in team_players:
                    for cat in CATEGORIES:
                        if cat not in punt_categories:
                            z_val = player['z_scores'].get(cat, 0)
                            if math.isfinite(z_val):
                                cat_totals[cat] += z_val
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': cat_totals
                }
    
    elif mode_type == 'team_stats_avg':
        # Режим по статистике команд (avg)
        # Получаем статистику всех игроков за период
        all_players_week_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        # Создаем словарь для быстрого поиска stats по имени
        stats_by_name = {p['name']: p['stats'] for p in all_players_week_stats}
        
        # Группируем игроков по командам (с учетом перемещений из all_players_list)
        players_by_team = {}
        for player in all_players_list:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            # Получаем stats для этого игрока
            player_stats = stats_by_name.get(player['name'], {})
            players_by_team[team_id].append({
                'name': player['name'],
                'stats': player_stats
            })
        
        # Рассчитываем статистику команды (как в /api/simulation)
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                team_raw_stats = calculate_raw_stats(team_players, punt_categories)
                
                # Преобразуем в формат для сравнения (только нужные категории)
                filtered_stats = {}
                for cat in CATEGORIES:
                    if cat not in punt_categories:
                        if cat in team_raw_stats:
                            filtered_stats[cat] = team_raw_stats[cat]
                        else:
                            filtered_stats[cat] = 0.0
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': filtered_stats
                }
            else:
                # Команда без игроков
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': {cat: 0.0 for cat in CATEGORIES}
                }
    
    if not team_stats:
        return {}
    
    # Симуляция "все против всех"
    team_ids = list(team_stats.keys())
    simulation_results = {tid: {'wins': 0, 'losses': 0, 'ties': 0} for tid in team_ids}
    
    for i in range(len(team_ids)):
        id1 = team_ids[i]
        stats1 = team_stats[id1]['stats']
        
        for j in range(i + 1, len(team_ids)):
            id2 = team_ids[j]
            stats2 = team_stats[id2]['stats']
            
            # Сравнение двух команд
            wins1 = 0
            wins2 = 0
            
            for cat in CATEGORIES:
                if cat not in punt_categories:
                    val1 = stats1.get(cat, 0.0)
                    val2 = stats2.get(cat, 0.0)
                    
                    # TO (Turnovers) - чем меньше, тем лучше
                    if cat == 'TO':
                        if val1 < val2: wins1 += 1
                        elif val2 < val1: wins2 += 1
                    else:
                        if val1 > val2: wins1 += 1
                        elif val2 > val1: wins2 += 1
            
            # Обновляем результаты
            if wins1 > wins2:
                simulation_results[id1]['wins'] += 1
                simulation_results[id2]['losses'] += 1
            elif wins2 > wins1:
                simulation_results[id2]['wins'] += 1
                simulation_results[id1]['losses'] += 1
            else:
                simulation_results[id1]['ties'] += 1
                simulation_results[id2]['ties'] += 1
    
    # Формируем итоговый список с винрейтом
    final_results = []
    for team_id, result in simulation_results.items():
        wins = result['wins']
        losses = result['losses']
        ties = result['ties']
        total_games = wins + losses + ties
        
        win_rate = (wins + 0.5 * ties) / total_games if total_games > 0 else 0
        
        final_results.append({
            'team_id': team_id,
            'name': team_stats[team_id]['name'],
            'wins': wins,
            'losses': losses,
            'ties': ties,
            'win_rate': win_rate
        })
    
    # Сортируем по винрейту
    final_results.sort(key=lambda x: x['win_rate'], reverse=True)
    
    # Создаем словарь {team_id: rank}
    ranks = {}
    for rank, team_result in enumerate(final_results, 1):
        ranks[team_result['team_id']] = rank
    
    return ranks


def calculate_category_rankings(all_players_list, team_id, league_meta, period, exclude_ir, punt_categories):
    """
    Рассчитывает позиции команды по категориям в лиге.
    Аналогично логике из /api/dashboard/{team_id}/category-rankings.
    
    Args:
        all_players_list: Список всех игроков лиги (с учетом или без учета трейда)
        team_id: ID команды для которой рассчитываем позиции
        league_meta: Экземпляр LeagueMetadata
        period: Период для расчета
        exclude_ir: Исключать ли игроков на IR
        punt_categories: Список категорий для исключения (punt)
    
    Returns:
        dict: Словарь {category: rank} где rank - позиция в лиге (1 = первое место)
    """
    # Получаем статистику всех игроков за период
    all_players_week_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    
    # Создаем словарь для быстрого поиска stats по имени
    stats_by_name = {p['name']: p['stats'] for p in all_players_week_stats}
    
    # Группируем игроков по командам (с учетом перемещений из all_players_list)
    players_by_team = {}
    for player in all_players_list:
        team_id_player = player['team_id']
        if team_id_player not in players_by_team:
            players_by_team[team_id_player] = []
        # Получаем stats для этого игрока
        player_stats = stats_by_name.get(player['name'], {})
        players_by_team[team_id_player].append({
            'name': player['name'],
            'stats': player_stats
        })
    
    # Получаем все команды
    teams = league_meta.get_teams()
    
    # Рассчитываем статистику для каждой команды
    team_stats = {}
    for team_obj in teams:
        if team_obj.team_id in players_by_team:
            team_players = players_by_team[team_obj.team_id]
            team_raw_stats = calculate_team_raw_stats(team_players)
            
            # Фильтруем только нужные категории
            filtered_stats = {}
            for cat in CATEGORIES:
                if cat not in punt_categories:
                    if cat in team_raw_stats:
                        filtered_stats[cat] = team_raw_stats[cat]
                    else:
                        filtered_stats[cat] = 0.0
            
            team_stats[team_obj.team_id] = {
                'name': team_obj.team_name,
                'stats': filtered_stats
            }
        else:
            # Команда без игроков
            team_stats[team_obj.team_id] = {
                'name': team_obj.team_name,
                'stats': {cat: 0.0 for cat in CATEGORIES if cat not in punt_categories}
            }
    
    if team_id not in team_stats:
        return {}
    
    my_team_stats = team_stats[team_id]['stats']
    category_rankings = {}
    
    # Рассчитываем позицию по каждой категории
    for cat in CATEGORIES:
        if cat in punt_categories:
            continue
            
        # Собираем значения всех команд по этой категории
        category_values = []
        for tid, team_data in team_stats.items():
            value = team_data['stats'].get(cat, 0.0)
            category_values.append({
                'team_id': tid,
                'value': value
            })
        
        # Сортируем по убыванию (больше = лучше)
        category_values.sort(key=lambda x: x['value'], reverse=True)
        
        # Находим позицию нашей команды
        my_value = my_team_stats.get(cat, 0.0)
        rank = 1
        for team_data in category_values:
            if team_data['team_id'] == team_id:
                break
            if team_data['value'] > my_value:
                rank += 1
        
        category_rankings[cat] = rank
    
    return category_rankings

