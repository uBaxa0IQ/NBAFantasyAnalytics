"""
Роутер для симуляций матчапов.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.config import CATEGORIES
from core.z_score import calculate_z_scores
from utils.calculations import calculate_team_category_z, calculate_team_raw_stats, select_top_n_players
from typing import Optional, List
import math

router = APIRouter(prefix="/api", tags=["simulation"])


@router.get("/simulation/{week}")
def get_simulation(
    week: int,
    weeks_count: int = None,
    mode: str = "matchup",
    period: str = "2026_total",
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_players: Optional[str] = None,
    custom_team_id: Optional[int] = None,
    league_meta=Depends(get_league_meta)
):
    """Получает результаты симуляции матчапов для всех команд."""
    # Получаем список всех команд
    teams = league_meta.get_teams()
    team_stats = {}
    
    if mode == "matchup":
        # Режим по матчапам (текущий)
        # Если weeks_count не указан, используем текущую неделю (все недели с начала)
        if weeks_count is None:
            weeks_count = week
        
        # Ограничиваем weeks_count текущей неделей
        weeks_count = min(weeks_count, week)
        weeks_count = max(weeks_count, 1)  # Минимум 1 неделя
        
        for team in teams:
            # Собираем статистику за N недель
            all_weeks_stats = []
            
            for w in range(week - weeks_count + 1, week + 1):
                if w < 1:
                    continue
                box = league_meta.get_matchup_box_score(w, team.team_id)
                if box:
                    stats = league_meta.filter_stats_by_categories(box['totals'])
                    all_weeks_stats.append(stats)
            
            if not all_weeks_stats:
                continue
            
            # Усредняем статистику по всем неделям
            avg_stats = {}
            
            for cat in CATEGORIES:
                values = [s.get(cat, 0.0) for s in all_weeks_stats if cat in s]
                avg_stats[cat] = sum(values) / len(values) if values else 0.0
            
            team_stats[team.team_id] = {
                'name': team.team_name,
                'stats': avg_stats
            }
    
    elif mode == "team_stats_avg":
        # Режим по статистике команд (avg)
        # Определяем exclude_ir на основе simulation_mode
        exclude_ir = (simulation_mode == "exclude_ir")
        
        # Получаем статистику всех игроков за период
        all_players = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        # Группируем игроков по командам
        players_by_team = {}
        for player in all_players:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
        # Если режим "top_n", применяем логику выбора топ-N игроков
        if simulation_mode == "top_n":
            # Парсим custom_team_players из строки в список
            custom_players_list = None
            if custom_team_players:
                custom_players_list = [name.strip() for name in custom_team_players.split(',') if name.strip()]
            
            # Получаем Z-scores для всех игроков (для сортировки)
            z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
            z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
            
            # Применяем логику выбора топ-N для каждой команды
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    
                    # Для custom_team_id используем выбранных игроков или топ-N
                    if team.team_id == custom_team_id and custom_players_list:
                        # Фильтруем только выбранных игроков
                        selected_players = [p for p in team_players if p['name'] in custom_players_list]
                        team_players = selected_players
                    else:
                        # Выбираем топ-N игроков
                        team_players = select_top_n_players(
                            team_players, 
                            top_n_players, 
                            punt_categories=[], 
                            z_scores_data=z_scores_by_name
                        )
                    
                    players_by_team[team.team_id] = team_players
        
        # Рассчитываем статистику для каждой команды
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                team_raw_stats = calculate_team_raw_stats(team_players)
                
                # Преобразуем в формат для сравнения (только нужные категории)
                filtered_stats = {}
                for cat in CATEGORIES:
                    if cat in team_raw_stats:
                        filtered_stats[cat] = team_raw_stats[cat]
                    else:
                        filtered_stats[cat] = 0.0
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': filtered_stats
                }
    
    elif mode == "z_scores":
        # Режим по Z-score
        # Определяем exclude_ir на основе simulation_mode
        exclude_ir = (simulation_mode == "exclude_ir")
        
        # Получаем Z-scores всех игроков
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        
        if not z_data['players']:
            return {"error": "No data found"}
        
        # Группируем игроков по командам
        players_by_team = {}
        for player in z_data['players']:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
        # Если режим "top_n", применяем логику выбора топ-N игроков
        if simulation_mode == "top_n":
            z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
            
            # Применяем логику выбора топ-N для каждой команды
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    
                    # Для custom_team_id используем выбранных игроков или топ-N
                    if team.team_id == custom_team_id and custom_team_players:
                        # Фильтруем только выбранных игроков
                        selected_players = [p for p in team_players if p['name'] in custom_team_players]
                        team_players = selected_players
                    else:
                        # Выбираем топ-N игроков
                        team_players = select_top_n_players(
                            team_players, 
                            top_n_players, 
                            punt_categories=[], 
                            z_scores_data=z_scores_by_name
                        )
                    
                    players_by_team[team.team_id] = team_players
        
        # Рассчитываем Z-scores для каждой команды
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                team_cats = calculate_team_category_z(team_players)
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': team_cats
                }
    
    else:
        return {"error": f"Unknown mode: {mode}"}
            
    if not team_stats:
        return {"error": "No stats found"}
        
    # Симуляция "все против всех"
    results = []
    
    # Преобразуем dict в list для удобного перебора
    teams_list = list(team_stats.values())
    team_ids = list(team_stats.keys())
    
    simulation_results = {tid: {'wins': 0, 'losses': 0, 'ties': 0, 'name': team_stats[tid]['name']} for tid in team_ids}
    
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
                
    # Формируем итоговый список
    final_results = []
    for team_id, result in simulation_results.items():
        wins = result['wins']
        losses = result['losses']
        ties = result['ties']
        total_games = wins + losses + ties
        
        # Винрейт: ничья = 0.5 победы
        win_rate = (wins + 0.5 * ties) / total_games if total_games > 0 else 0
        
        final_results.append({
            'name': result['name'],
            'wins': wins,
            'losses': losses,
            'ties': ties,
            'win_rate': round(win_rate * 100, 1)  # В процентах
        })
    
    # Сортируем по винрейту
    final_results.sort(key=lambda x: x['win_rate'], reverse=True)
    
    return final_results


@router.get("/simulation-detailed/{week}")
def get_simulation_detailed(
    week: int,
    weeks_count: int = None,
    mode: str = "matchup",
    period: str = "2026_total",
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_players: Optional[str] = None,
    custom_team_id: Optional[int] = None,
    league_meta=Depends(get_league_meta)
):
    """
    Расширенная симуляция с детальными результатами матчапов для каждой команды.
    """
    # Получаем список всех команд
    teams = league_meta.get_teams()
    team_stats = {}
    
    if mode == "matchup":
        # Режим по матчапам (текущий)
        if weeks_count is None:
            weeks_count = week
        
        weeks_count = min(weeks_count, week)
        weeks_count = max(weeks_count, 1)
        
        for team in teams:
            all_weeks_stats = []
            
            for w in range(week - weeks_count + 1, week + 1):
                if w < 1:
                    continue
                box = league_meta.get_matchup_box_score(w, team.team_id)
                if box:
                    stats = league_meta.filter_stats_by_categories(box['totals'])
                    all_weeks_stats.append(stats)
            
            if not all_weeks_stats:
                continue
            
            # Усредняем статистику
            avg_stats = {}
            for cat in CATEGORIES:
                values = [s.get(cat, 0.0) for s in all_weeks_stats if cat in s]
                avg_stats[cat] = sum(values) / len(values) if values else 0.0
            
            team_stats[team.team_id] = {
                'name': team.team_name,
                'stats': avg_stats
            }
    
    elif mode == "team_stats_avg":
        # Режим по статистике команд (avg)
        # Определяем exclude_ir на основе simulation_mode
        exclude_ir = (simulation_mode == "exclude_ir")
        
        all_players = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        players_by_team = {}
        for player in all_players:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
        # Если режим "top_n", применяем логику выбора топ-N игроков
        if simulation_mode == "top_n":
            # Парсим custom_team_players из строки в список
            custom_players_list = None
            if custom_team_players:
                custom_players_list = [name.strip() for name in custom_team_players.split(',') if name.strip()]
            
            # Получаем Z-scores для всех игроков (для сортировки)
            z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
            z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
            
            # Применяем логику выбора топ-N для каждой команды
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    
                    # Для custom_team_id используем выбранных игроков или топ-N
                    if team.team_id == custom_team_id and custom_players_list:
                        # Фильтруем только выбранных игроков
                        selected_players = [p for p in team_players if p['name'] in custom_players_list]
                        team_players = selected_players
                    else:
                        # Выбираем топ-N игроков
                        team_players = select_top_n_players(
                            team_players, 
                            top_n_players, 
                            punt_categories=[], 
                            z_scores_data=z_scores_by_name
                        )
                    
                    players_by_team[team.team_id] = team_players
        
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                team_raw_stats = calculate_team_raw_stats(team_players)
                
                filtered_stats = {}
                for cat in CATEGORIES:
                    if cat in team_raw_stats:
                        filtered_stats[cat] = team_raw_stats[cat]
                    else:
                        filtered_stats[cat] = 0.0
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': filtered_stats
                }
    
    elif mode == "z_scores":
        # Режим по Z-score
        # Определяем exclude_ir на основе simulation_mode
        exclude_ir = (simulation_mode == "exclude_ir")
        
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        
        if not z_data['players']:
            return {"error": "No data found"}
        
        players_by_team = {}
        for player in z_data['players']:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
        # Если режим "top_n", применяем логику выбора топ-N игроков
        if simulation_mode == "top_n":
            z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
            
            # Применяем логику выбора топ-N для каждой команды
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    
                    # Для custom_team_id используем выбранных игроков или топ-N
                    if team.team_id == custom_team_id and custom_team_players:
                        # Фильтруем только выбранных игроков
                        selected_players = [p for p in team_players if p['name'] in custom_team_players]
                        team_players = selected_players
                    else:
                        # Выбираем топ-N игроков
                        team_players = select_top_n_players(
                            team_players, 
                            top_n_players, 
                            punt_categories=[], 
                            z_scores_data=z_scores_by_name
                        )
                    
                    players_by_team[team.team_id] = team_players
        
        for team in teams:
            if team.team_id in players_by_team:
                team_players = players_by_team[team.team_id]
                team_cats = calculate_team_category_z(team_players)
                
                team_stats[team.team_id] = {
                    'name': team.team_name,
                    'stats': team_cats
                }
    
    else:
        return {"error": f"Unknown mode: {mode}"}
            
    if not team_stats:
        return {"error": "No stats found"}
        
    # Симуляция "все против всех" с сохранением детальных результатов
    team_ids = list(team_stats.keys())
    
    # Структура для хранения результатов каждой команды
    simulation_results = {}
    for tid in team_ids:
        simulation_results[tid] = {
            'wins': 0,
            'losses': 0,
            'ties': 0,
            'name': team_stats[tid]['name'],
            'matchups': []  # Детальные результаты всех матчапов
        }
    
    # Проводим все матчи
    for i in range(len(team_ids)):
        id1 = team_ids[i]
        stats1 = team_stats[id1]['stats']
        
        for j in range(i + 1, len(team_ids)):
            id2 = team_ids[j]
            stats2 = team_stats[id2]['stats']
            
            # Сравнение двух команд по категориям
            wins1 = 0
            wins2 = 0
            category_results = {}
            
            for cat in CATEGORIES:
                val1 = stats1.get(cat, 0.0)
                val2 = stats2.get(cat, 0.0)
                
                # TO (Turnovers) - чем меньше, тем лучше
                if cat == 'TO':
                    if val1 < val2:
                        wins1 += 1
                        category_results[cat] = 'win'
                    elif val2 < val1:
                        wins2 += 1
                        category_results[cat] = 'loss'
                    else:
                        category_results[cat] = 'tie'
                else:
                    if val1 > val2:
                        wins1 += 1
                        category_results[cat] = 'win'
                    elif val2 > val1:
                        wins2 += 1
                        category_results[cat] = 'loss'
                    else:
                        category_results[cat] = 'tie'
            
            # Определяем результат матчапа
            if wins1 > wins2:
                result1 = 'win'
                result2 = 'loss'
                simulation_results[id1]['wins'] += 1
                simulation_results[id2]['losses'] += 1
            elif wins2 > wins1:
                result1 = 'loss'
                result2 = 'win'
                simulation_results[id2]['wins'] += 1
                simulation_results[id1]['losses'] += 1
            else:
                result1 = 'tie'
                result2 = 'tie'
                simulation_results[id1]['ties'] += 1
                simulation_results[id2]['ties'] += 1
            
            # Сохраняем детальный результат для обеих команд
            simulation_results[id1]['matchups'].append({
                'opponent_id': id2,
                'opponent_name': team_stats[id2]['name'],
                'result': result1,
                'score': f"{wins1}-{wins2}",
                'categories': category_results.copy()
            })
            
            # Инвертируем результаты категорий для второй команды
            inverted_categories = {}
            for cat, res in category_results.items():
                if res == 'win':
                    inverted_categories[cat] = 'loss'
                elif res == 'loss':
                    inverted_categories[cat] = 'win'
                else:
                    inverted_categories[cat] = 'tie'
            
            simulation_results[id2]['matchups'].append({
                'opponent_id': id1,
                'opponent_name': team_stats[id1]['name'],
                'result': result2,
                'score': f"{wins2}-{wins1}",
                'categories': inverted_categories
            })
    
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
            'name': result['name'],
            'wins': wins,
            'losses': losses,
            'ties': ties,
            'win_rate': round(win_rate * 100, 1),
            'matchups': result['matchups']  # Детальные результаты
        })
    
    # Сортируем по винрейту
    final_results.sort(key=lambda x: x['win_rate'], reverse=True)
    
    return {
        'mode': mode,
        'week': week,
        'period': period,
        'results': final_results
    }

