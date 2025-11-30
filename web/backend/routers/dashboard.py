"""
Роутер для дашборда команд.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
from utils.calculations import calculate_team_raw_stats
import math

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

from utils.calculations import calculate_team_raw_stats


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
    
    # Получаем позицию команды в лиге (из реальных данных ESPN)
    # В ESPN API позиция команды обычно доступна через поле standing или через standings
    league_position = None
    try:
        # Способ 1: Прямое поле у команды (самый надежный способ)
        # Проверяем различные возможные названия полей
        possible_fields = ['standing', 'rank', 'overall_rank', 'final_standing', 'standing_position']
        for field in possible_fields:
            if hasattr(team, field):
                value = getattr(team, field)
                if value is not None and isinstance(value, (int, float)):
                    league_position = int(value)
                    break
        
        # Способ 2: Используем standings из league (если доступно)
        if league_position is None and hasattr(league_meta.league, 'standings'):
            standings = league_meta.league.standings
            if standings:
                # standings может быть списком команд, отсортированных по позиции
                if isinstance(standings, list):
                    for idx, standing_team in enumerate(standings):
                        team_id_from_standing = None
                        if hasattr(standing_team, 'team_id'):
                            team_id_from_standing = standing_team.team_id
                        elif isinstance(standing_team, dict):
                            team_id_from_standing = standing_team.get('team_id')
                        
                        if team_id_from_standing == team_id:
                            league_position = idx + 1
                            break
        
        # Способ 3: Если league.teams уже отсортированы по позиции, используем индекс
        if league_position is None:
            all_teams = league_meta.get_teams()
            # Проверяем, отсортированы ли команды по позиции (по wins убывание)
            # Если да, то индекс в списке = позиция
            for idx, t in enumerate(all_teams):
                if t.team_id == team_id:
                    # Проверяем, отсортирован ли список по wins
                    if idx > 0:
                        prev_wins = getattr(all_teams[idx - 1], 'wins', 0)
                        curr_wins = getattr(t, 'wins', 0)
                        if prev_wins >= curr_wins:
                            # Похоже, что команды отсортированы по позиции
                            league_position = idx + 1
                            break
        
        # Способ 4: Вычисляем позицию на основе рекорда (последний вариант)
        if league_position is None:
            all_teams = league_meta.get_teams()
            teams_with_records = []
            
            for t in all_teams:
                wins = getattr(t, 'wins', 0)
                losses = getattr(t, 'losses', 0)
                ties = getattr(t, 'ties', 0)
                teams_with_records.append({
                    'team_id': t.team_id,
                    'team_name': t.team_name,
                    'wins': wins,
                    'losses': losses,
                    'ties': ties,
                    'win_pct': wins / (wins + losses + ties) if (wins + losses + ties) > 0 else 0
                })
            
            # Сортируем по винрейту (убывание), затем по победам
            teams_with_records.sort(key=lambda x: (x['win_pct'], x['wins']), reverse=True)
            
            # Находим позицию нашей команды
            for idx, team_record in enumerate(teams_with_records):
                if team_record['team_id'] == team_id:
                    league_position = idx + 1
                    break
                    
    except Exception as e:
        print(f"Error getting league position: {e}")
        import traceback
        traceback.print_exc()
        league_position = None
    
    return {
        "team_id": team_id,
        "team_name": team.team_name,
        "league_position": league_position,
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


@router.get("/{team_id}/category-rankings")
def get_category_rankings(
    team_id: int,
    period: str = "2026_total",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """
    Получает рейтинг команды по категориям на основе avg статистики.
    Возвращает топ-3 сильных категорий и полный рейтинг по всем категориям.
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем avg статистику всех игроков
    all_players = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    
    if not all_players:
        return {"error": "No data found"}
    
    # Группируем игроков по командам
    players_by_team = {}
    for player in all_players:
        player_team_id = player['team_id']
        if player_team_id not in players_by_team:
            players_by_team[player_team_id] = []
        players_by_team[player_team_id].append({
            'name': player['name'],
            'stats': player['stats']
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
                'stats': {cat: 0.0 for cat in CATEGORIES}
            }
    
    if team_id not in team_stats:
        return {"error": "Team not found in stats"}
    
    total_teams = len(team_stats)
    my_team_stats = team_stats[team_id]['stats']
    
    # Рассчитываем рейтинг по каждой категории и собираем данные по всем командам
    all_rankings = []
    category_teams_data = {}  # Для хранения топ команд по каждой категории
    
    for cat in CATEGORIES:
        # Собираем значения всех команд по этой категории
        category_values = []
        for tid, team_data in team_stats.items():
            value = team_data['stats'].get(cat, 0.0)
            category_values.append({
                'team_id': tid,
                'team_name': team_data['name'],
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
        
        # Сохраняем топ команд для этой категории
        category_teams_data[cat] = [
            {
                'rank': idx + 1,
                'team_id': team['team_id'],
                'team_name': team['team_name'],
                'value': round(team['value'], 2)
            }
            for idx, team in enumerate(category_values)
        ]
        
        all_rankings.append({
            'category': cat,
            'rank': rank,
            'value': round(my_value, 2)
        })
    
    # Сортируем по рангу (лучшие позиции = меньший ранг) для определения топ-3
    # Если ранги равны, сортируем по значению
    all_rankings_sorted = sorted(all_rankings, key=lambda x: (x['rank'], -x['value']))
    top_categories = all_rankings_sorted[:3]
    
    return {
        'team_id': team_id,
        'team_name': team_stats[team_id]['name'],
        'top_categories': top_categories,
        'all_rankings': all_rankings,
        'category_teams': category_teams_data  # Топ команд по каждой категории
    }


@router.get("/{team_id}/position-history")
def get_position_history(
    team_id: int,
    period: str = "2026_total",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """
    Получает историю позиций команды в лиге по неделям на основе симуляции матчапов.
    Для каждой недели запускается симуляция "все против всех" и определяется позиция команды.
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем текущую неделю
    current_week = league_meta.league.currentMatchupPeriod
    
    # Список для хранения позиций по неделям
    position_history = []
    
    # Для каждой недели от 1 до текущей
    for week in range(1, current_week + 1):
        try:
            # Получаем все команды
            teams = league_meta.get_teams()
            team_stats = {}
            
            # Собираем статистику ТОЛЬКО за текущую неделю (не накопительно)
            for t in teams:
                # Получаем статистику только за эту конкретную неделю
                box = league_meta.get_matchup_box_score(week, t.team_id)
                if box:
                    stats = league_meta.filter_stats_by_categories(box['totals'])
                    team_stats[t.team_id] = {
                        'name': t.team_name,
                        'stats': stats
                    }
            
            if not team_stats or team_id not in team_stats:
                # Если нет данных для этой недели, пропускаем
                continue
            
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
            for tid, result in simulation_results.items():
                wins = result['wins']
                losses = result['losses']
                ties = result['ties']
                total_games = wins + losses + ties
                
                win_rate = (wins + 0.5 * ties) / total_games if total_games > 0 else 0
                
                final_results.append({
                    'team_id': tid,
                    'name': team_stats[tid]['name'],
                    'wins': wins,
                    'losses': losses,
                    'ties': ties,
                    'win_rate': win_rate
                })
            
            # Сортируем по винрейту
            final_results.sort(key=lambda x: (x['win_rate'], x['wins']), reverse=True)
            
            # Находим позицию нашей команды
            position = None
            for idx, team_result in enumerate(final_results):
                if team_result['team_id'] == team_id:
                    position = idx + 1
                    break
            
            if position is not None:
                position_history.append({
                    'week': week,
                    'position': position
                })
        except Exception as e:
            # Если ошибка для конкретной недели, пропускаем её
            print(f"Error calculating position for week {week}: {e}")
            continue
    
    return {
        'team_id': team_id,
        'team_name': team.team_name,
        'position_history': position_history
    }

