from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys
import os

# Добавляем путь к проекту и core
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'core'))

from core.league_metadata import LeagueMetadata
from pydantic import BaseModel
from typing import List

app = FastAPI()

# Настройка CORS
# Для продакшена используйте переменную окружения CORS_ORIGINS (через запятую)
# Например: CORS_ORIGINS=http://yourdomain.com,http://www.yourdomain.com
import os
cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env:
    allowed_origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
else:
    # По умолчанию для разработки
    allowed_origins = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Docker frontend (old port)
        "http://localhost:3001",  # Docker frontend (new port)
        "http://127.0.0.1:3000",  # Docker frontend alternative
        "http://127.0.0.1:3001",  # Docker frontend alternative
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация league_meta
league_meta = LeagueMetadata()
league_meta.connect_to_league()


@app.get("/")
def root():
    return {"message": "NBA Fantasy Analytics API"}

@app.get("/api/teams")
def get_teams():
    teams = league_meta.get_teams()
    return [{"team_id": t.team_id, "team_name": t.team_name} for t in teams]

@app.post("/api/refresh-league")
def refresh_league():
    """
    Обновляет данные лиги из ESPN API.
    Перезагружает информацию о командах, игроках и их статусах (включая травмы).
    
    Returns:
        Словарь с результатом обновления:
        {
            "success": bool,
            "message": str
        }
    """
    try:
        success = league_meta.refresh_league()
        if success:
            return {
                "success": True,
                "message": "Данные лиги успешно обновлены"
            }
        else:
            return {
                "success": False,
                "message": "Ошибка при обновлении данных лиги"
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Ошибка при обновлении данных: {str(e)}"
        }

@app.get("/api/weeks")
def get_weeks():
    weeks = list(range(1, league_meta.league.currentMatchupPeriod + 1))
    return {
        "weeks": weeks,
        "current_week": league_meta.league.currentMatchupPeriod
    }

@app.get("/api/analytics/{team_id}")
def get_analytics(team_id: int, period: str = "2026_total", exclude_ir: bool = False):
    from core.z_score import calculate_z_scores
    import math
    
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    # Добавляем полную статистику к игрокам
    all_players_with_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
    stats_by_name = {p['name']: p['stats'] for p in all_players_with_stats}
    
    # Добавляем статистику к каждому игроку
    for player in team_players:
        player_stats = stats_by_name.get(player['name'], {})
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

@app.get("/api/simulation/{week}")
def get_simulation(week: int, weeks_count: int = None, mode: str = "matchup", period: str = "2026_total", exclude_ir: bool = False):
    from core.config import CATEGORIES
    from core.z_score import calculate_z_scores
    import math
    
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
        # Получаем статистику всех игроков за период
        all_players = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        # Функция для расчета статистики команды (как в trade-analysis)
        def calculate_team_raw_stats(team_players):
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
        
        # Группируем игроков по командам
        players_by_team = {}
        for player in all_players:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
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
        # Получаем Z-scores всех игроков
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        
        if not z_data['players']:
            return {"error": "No data found"}
        
        # Функция для расчета Z по категориям команды
        def calculate_team_category_z(team_players):
            cat_totals = {cat: 0 for cat in CATEGORIES}
            for player in team_players:
                for cat in CATEGORIES:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        cat_totals[cat] += z_val
            return cat_totals
        
        # Группируем игроков по командам
        players_by_team = {}
        for player in z_data['players']:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
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

@app.get("/api/free-agents")
def get_free_agents(period: str = "2026_total", position: str = None):
    import math
    from core.z_score import calculate_z_scores
    
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
        from core.z_score import COUNTING_CATEGORIES, PERCENTAGE_CATEGORIES
        from core.config import CATEGORIES
        
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

@app.get("/api/all-players")
def get_all_players(period: str = "2026_total", exclude_ir: bool = False):
    import math
    from core.z_score import calculate_z_scores
    
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

# Модель для анализа трейда
class TradeAnalysisRequest(BaseModel):
    my_team_id: int
    their_team_id: int
    i_give: List[str]  # Имена игроков
    i_receive: List[str]
    period: str = "2026_total"
    punt_categories: List[str] = []
    scope_mode: str = "team"  # "team" или "trade"
    exclude_ir: bool = False

# Модель для мультикомандных трейдов
class TeamTrade(BaseModel):
    team_id: int
    give: List[str]  # Имена игроков, которых отдает команда
    receive: List[str]  # Имена игроков, которых получает команда

class MultiTeamTradeRequest(BaseModel):
    trades: List[TeamTrade]  # Список команд и их трейдов
    period: str = "2026_total"
    punt_categories: List[str] = []
    exclude_ir: bool = False

@app.post("/api/trade-analysis")
def analyze_trade(request: TradeAnalysisRequest):
    from core.z_score import calculate_z_scores
    from core.config import CATEGORIES
    import math
    
    # Получаем Z-scores всех игроков
    data = calculate_z_scores(league_meta, request.period, exclude_ir=request.exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Получаем полные данные игроков со статистикой
    all_players_with_stats = league_meta.get_all_players_stats(request.period, 'avg', exclude_ir=request.exclude_ir)
    
    # Создаем словарь для быстрого поиска stats по имени игрока
    stats_by_name = {p['name']: p['stats'] for p in all_players_with_stats}
    
    # Добавляем stats к каждому игроку
    for player in data['players']:
        player['stats'] = stats_by_name.get(player['name'], {})

    
    # Фильтруем игроков по командам
    my_team_players = [p for p in data['players'] if p['team_id'] == request.my_team_id]
    their_team_players = [p for p in data['players'] if p['team_id'] == request.their_team_id]
    
    # Функция для расчета Total Z с учетом punt
    def calculate_total_z(players, punt_cats):
        total = 0
        for player in players:
            for cat in CATEGORIES:
                if cat not in punt_cats:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        total += z_val
        return total
    
    # Функция для расчета Z по категориям
    def calculate_category_z(players, punt_cats):
        cat_totals = {cat: 0 for cat in CATEGORIES}
        for player in players:
            for cat in CATEGORIES:
                if cat not in punt_cats:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        cat_totals[cat] += z_val
        return cat_totals
    
    # Функция для расчета реальных значений (raw stats) с взвешенными процентами
    def calculate_raw_stats(players, punt_cats):
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
    
    # Расчет "До трейда"
    my_before_z = calculate_total_z(my_team_players, request.punt_categories)
    their_before_z = calculate_total_z(their_team_players, request.punt_categories)
    
    my_before_cats = calculate_category_z(my_team_players, request.punt_categories)
    their_before_cats = calculate_category_z(their_team_players, request.punt_categories)
    
    my_before_raw = calculate_raw_stats(my_team_players, request.punt_categories)
    their_before_raw = calculate_raw_stats(their_team_players, request.punt_categories)
    
    # Найти игроков для обмена
    players_i_give = [p for p in my_team_players if p['name'] in request.i_give]
    players_i_receive = [p for p in their_team_players if p['name'] in request.i_receive]
    
    # Расчет "После трейда"
    # Моя команда: убрать отдаваемых, добавить получаемых
    my_after_players = [p for p in my_team_players if p['name'] not in request.i_give] + players_i_receive
    my_after_z = calculate_total_z(my_after_players, request.punt_categories)
    my_after_cats = calculate_category_z(my_after_players, request.punt_categories)
    my_after_raw = calculate_raw_stats(my_after_players, request.punt_categories)
    
    # Их команда: убрать отдаваемых, добавить получаемых
    their_after_players = [p for p in their_team_players if p['name'] not in request.i_receive] + players_i_give
    their_after_z = calculate_total_z(their_after_players, request.punt_categories)
    their_after_cats = calculate_category_z(their_after_players, request.punt_categories)
    their_after_raw = calculate_raw_stats(their_after_players, request.punt_categories)
    
    # Расчет для режима "Только трейд" (только игроки трейда)
    # Моя команда: до = отдаваемые, после = получаемые
    my_trade_before_z = calculate_total_z(players_i_give, request.punt_categories)
    my_trade_after_z = calculate_total_z(players_i_receive, request.punt_categories)
    my_trade_before_cats = calculate_category_z(players_i_give, request.punt_categories)
    my_trade_after_cats = calculate_category_z(players_i_receive, request.punt_categories)
    my_trade_before_raw = calculate_raw_stats(players_i_give, request.punt_categories)
    my_trade_after_raw = calculate_raw_stats(players_i_receive, request.punt_categories)
    
    # Их команда: до = получаемые (которые я получаю), после = отдаваемые (которые я отдаю)
    their_trade_before_z = calculate_total_z(players_i_receive, request.punt_categories)
    their_trade_after_z = calculate_total_z(players_i_give, request.punt_categories)
    their_trade_before_cats = calculate_category_z(players_i_receive, request.punt_categories)
    their_trade_after_cats = calculate_category_z(players_i_give, request.punt_categories)
    their_trade_before_raw = calculate_raw_stats(players_i_receive, request.punt_categories)
    their_trade_after_raw = calculate_raw_stats(players_i_give, request.punt_categories)
    
    # Формируем ответ
    my_team_name = my_team_players[0]['team_name'] if my_team_players else "Unknown"
    their_team_name = their_team_players[0]['team_name'] if their_team_players else "Unknown"
    
    # Детализация по категориям для моей команды (Z-scores)
    my_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            my_categories[cat] = {
                "before": round(my_before_cats[cat], 2),
                "after": round(my_after_cats[cat], 2),
                "delta": round(my_after_cats[cat] - my_before_cats[cat], 2)
            }
    
    # Детализация по категориям для их команды (Z-scores)
    their_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            their_categories[cat] = {
                "before": round(their_before_cats[cat], 2),
                "after": round(their_after_cats[cat], 2),
                "delta": round(their_after_cats[cat] - their_before_cats[cat], 2)
            }
    
    # Детализация RAW STATS для моей команды
    my_raw_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            my_raw_categories[cat] = {
                "before": round(my_before_raw.get(cat, 0), 2),
                "after": round(my_after_raw.get(cat, 0), 2),
                "delta": round(my_after_raw.get(cat, 0) - my_before_raw.get(cat, 0), 2)
            }
    
    # Детализация RAW STATS для их команды
    their_raw_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            their_raw_categories[cat] = {
                "before": round(their_before_raw.get(cat, 0), 2),
                "after": round(their_after_raw.get(cat, 0), 2),
                "delta": round(their_after_raw.get(cat, 0) - their_before_raw.get(cat, 0), 2)
            }
    
    # Детализация для режима "Только трейд" - моя команда
    my_trade_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            my_trade_categories[cat] = {
                "before": round(my_trade_before_cats[cat], 2),
                "after": round(my_trade_after_cats[cat], 2),
                "delta": round(my_trade_after_cats[cat] - my_trade_before_cats[cat], 2)
            }
    
    my_trade_raw_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            my_trade_raw_categories[cat] = {
                "before": round(my_trade_before_raw.get(cat, 0), 2),
                "after": round(my_trade_after_raw.get(cat, 0), 2),
                "delta": round(my_trade_after_raw.get(cat, 0) - my_trade_before_raw.get(cat, 0), 2)
            }
    
    # Детализация для режима "Только трейд" - их команда
    their_trade_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            their_trade_categories[cat] = {
                "before": round(their_trade_before_cats[cat], 2),
                "after": round(their_trade_after_cats[cat], 2),
                "delta": round(their_trade_after_cats[cat] - their_trade_before_cats[cat], 2)
            }
    
    their_trade_raw_categories = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            their_trade_raw_categories[cat] = {
                "before": round(their_trade_before_raw.get(cat, 0), 2),
                "after": round(their_trade_after_raw.get(cat, 0), 2),
                "delta": round(their_trade_after_raw.get(cat, 0) - their_trade_before_raw.get(cat, 0), 2)
            }
    
    # Формируем имена для режима трейда (используем названия команд)
    my_trade_name = my_team_name
    their_trade_name = their_team_name
    
    # Функция для расчета симуляции и получения мест команд (использует head-to-head как в /api/simulation)
    def calculate_simulation_ranks(all_players_list, mode_type):
        """
        Рассчитывает симуляцию для всех команд и возвращает места в рейтинге.
        Использует тот же метод, что и /api/simulation - симуляцию "все против всех".
        
        Args:
            all_players_list: Список всех игроков лиги (с учетом или без учета трейда)
            mode_type: 'z_scores' или 'team_stats_avg'
        
        Returns:
            Словарь {team_id: rank} где rank - место в рейтинге (1 = первое место)
        """
        from core.config import CATEGORIES
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
                            if cat not in request.punt_categories:
                                z_val = player['z_scores'].get(cat, 0)
                                if math.isfinite(z_val):
                                    cat_totals[cat] += z_val
                    
                    team_stats[team.team_id] = {
                        'name': team.team_name,
                        'stats': cat_totals
                    }
        
        elif mode_type == 'team_stats_avg':
            # Режим по статистике команд (avg)
            # Группируем игроков по командам
            players_by_team = {}
            for player in all_players_list:
                team_id = player['team_id']
                if team_id not in players_by_team:
                    players_by_team[team_id] = []
                players_by_team[team_id].append(player)
            
            # Рассчитываем статистику для каждой команды
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    team_raw_stats = calculate_raw_stats(team_players, request.punt_categories)
                    
                    # Преобразуем в формат для сравнения
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
                    if cat not in request.punt_categories:
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
    
    # Создаем списки игроков ДО и ПОСЛЕ трейда
    # ДО трейда: все игроки как есть
    all_players_before = data['players'].copy()
    
    # ПОСЛЕ трейда: меняем игроков в моей и их команде
    all_players_after = []
    for player in data['players']:
        player_copy = player.copy()
        
        # Если это игрок, которого я отдаю - переводим в их команду
        if player['team_id'] == request.my_team_id and player['name'] in request.i_give:
            player_copy['team_id'] = request.their_team_id
            player_copy['team_name'] = their_team_name
            all_players_after.append(player_copy)
        # Если это игрок, которого я получаю - переводим в мою команду
        elif player['team_id'] == request.their_team_id and player['name'] in request.i_receive:
            player_copy['team_id'] = request.my_team_id
            player_copy['team_name'] = my_team_name
            all_players_after.append(player_copy)
        # Все остальные игроки остаются как есть
        else:
            all_players_after.append(player_copy)
    
    # Рассчитываем места для обоих режимов ДО и ПОСЛЕ трейда
    ranks_before_z = calculate_simulation_ranks(all_players_before, 'z_scores')
    ranks_after_z = calculate_simulation_ranks(all_players_after, 'z_scores')
    ranks_before_avg = calculate_simulation_ranks(all_players_before, 'team_stats_avg')
    ranks_after_avg = calculate_simulation_ranks(all_players_after, 'team_stats_avg')
    
    # Формируем данные о местах для ответа
    simulation_ranks = {
        'z_scores': {
            'my_team': {
                'before': ranks_before_z.get(request.my_team_id, None),
                'after': ranks_after_z.get(request.my_team_id, None),
                'delta': (ranks_after_z.get(request.my_team_id, 0) - ranks_before_z.get(request.my_team_id, 0)) if (request.my_team_id in ranks_after_z and request.my_team_id in ranks_before_z) else None
            },
            'their_team': {
                'before': ranks_before_z.get(request.their_team_id, None),
                'after': ranks_after_z.get(request.their_team_id, None),
                'delta': (ranks_after_z.get(request.their_team_id, 0) - ranks_before_z.get(request.their_team_id, 0)) if (request.their_team_id in ranks_after_z and request.their_team_id in ranks_before_z) else None
            }
        },
        'team_stats_avg': {
            'my_team': {
                'before': ranks_before_avg.get(request.my_team_id, None),
                'after': ranks_after_avg.get(request.my_team_id, None),
                'delta': (ranks_after_avg.get(request.my_team_id, 0) - ranks_before_avg.get(request.my_team_id, 0)) if (request.my_team_id in ranks_after_avg and request.my_team_id in ranks_before_avg) else None
            },
            'their_team': {
                'before': ranks_before_avg.get(request.their_team_id, None),
                'after': ranks_after_avg.get(request.their_team_id, None),
                'delta': (ranks_after_avg.get(request.their_team_id, 0) - ranks_before_avg.get(request.their_team_id, 0)) if (request.their_team_id in ranks_after_avg and request.their_team_id in ranks_before_avg) else None
            }
        }
    }
    
    return {
        "my_team": {
            "name": my_team_name,
            "before_z": round(my_before_z, 2),
            "after_z": round(my_after_z, 2),
            "delta": round(my_after_z - my_before_z, 2),
            "categories": my_categories,
            "raw_categories": my_raw_categories
        },
        "their_team": {
            "name": their_team_name,
            "before_z": round(their_before_z, 2),
            "after_z": round(their_after_z, 2),
            "delta": round(their_after_z - their_before_z, 2),
            "categories": their_categories,
            "raw_categories": their_raw_categories
        },
        "my_trade": {
            "name": my_trade_name,
            "before_z": round(my_trade_before_z, 2),
            "after_z": round(my_trade_after_z, 2),
            "delta": round(my_trade_after_z - my_trade_before_z, 2),
            "categories": my_trade_categories,
            "raw_categories": my_trade_raw_categories
        },
        "their_trade": {
            "name": their_trade_name,
            "before_z": round(their_trade_before_z, 2),
            "after_z": round(their_trade_after_z, 2),
            "delta": round(their_trade_after_z - their_trade_before_z, 2),
            "categories": their_trade_categories,
            "raw_categories": their_trade_raw_categories
        },
        "simulation_ranks": simulation_ranks
    }

@app.post("/api/multi-team-trade-analysis")
def analyze_multi_team_trade(request: MultiTeamTradeRequest):
    """
    Анализ мультикомандного трейда.
    Поддерживает любое количество команд, участвующих в трейде.
    """
    from core.z_score import calculate_z_scores
    from core.config import CATEGORIES
    import math
    
    # Валидация
    validation_errors = []
    
    # 1. Проверка уникальности команд
    team_ids = [t.team_id for t in request.trades]
    if len(team_ids) != len(set(team_ids)):
        validation_errors.append("Дублирующиеся команды в трейде")
    
    # 2. Проверка баланса: все отданные игроки должны быть получены
    all_given = []
    all_received = []
    for trade in request.trades:
        all_given.extend(trade.give)
        all_received.extend(trade.receive)
    
    # Проверка уникальности игроков
    if len(all_given) != len(set(all_given)):
        validation_errors.append("Некоторые игроки отдаются несколько раз")
    if len(all_received) != len(set(all_received)):
        validation_errors.append("Некоторые игроки получаются несколько раз")
    
    # Проверка баланса
    if sorted(all_given) != sorted(all_received):
        validation_errors.append(f"Несбалансированный трейд: отдано {len(all_given)}, получено {len(all_received)}")
    
    # 3. Проверка, что игрок не может быть и в give и в receive одной команды
    for trade in request.trades:
        overlap = set(trade.give) & set(trade.receive)
        if overlap:
            validation_errors.append(f"Команда {trade.team_id}: игроки {overlap} одновременно отдаются и получаются")
    
    if validation_errors:
        return {
            "error": "Validation failed",
            "validation_errors": validation_errors
        }
    
    # Создаем маппинг: player_name -> new_team_id
    player_movements = {}
    for trade in request.trades:
        for player_name in trade.give:
            # Находим, какая команда получает этого игрока
            receiving_team = None
            for other_trade in request.trades:
                if player_name in other_trade.receive:
                    receiving_team = other_trade.team_id
                    break
            if receiving_team:
                player_movements[player_name] = receiving_team
    
    # Получаем Z-scores всех игроков
    data = calculate_z_scores(league_meta, request.period, exclude_ir=request.exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Получаем полные данные игроков со статистикой
    all_players_with_stats = league_meta.get_all_players_stats(request.period, 'avg', exclude_ir=request.exclude_ir)
    stats_by_name = {p['name']: p['stats'] for p in all_players_with_stats}
    
    # Добавляем stats к каждому игроку
    for player in data['players']:
        player['stats'] = stats_by_name.get(player['name'], {})
    
    # Функции расчета (те же, что в analyze_trade)
    def calculate_total_z(players, punt_cats):
        total = 0
        for player in players:
            for cat in CATEGORIES:
                if cat not in punt_cats:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        total += z_val
        return total
    
    def calculate_category_z(players, punt_cats):
        cat_totals = {cat: 0 for cat in CATEGORIES}
        for player in players:
            for cat in CATEGORIES:
                if cat not in punt_cats:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        cat_totals[cat] += z_val
        return cat_totals
    
    def calculate_raw_stats(players, punt_cats):
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
            stats = player.get('stats', {})
            
            for cat in counting_stats:
                if cat not in punt_cats:
                    val = stats.get(cat, 0)
                    counting_stats[cat] += val if math.isfinite(val) else 0
            
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
        
        raw_stats = counting_stats.copy()
        raw_stats['FG%'] = (fg_makes / fg_attempts * 100) if fg_attempts > 0 else 0
        raw_stats['FT%'] = (ft_makes / ft_attempts * 100) if ft_attempts > 0 else 0
        raw_stats['3PT%'] = (three_makes / three_attempts * 100) if three_attempts > 0 else 0
        raw_stats['A/TO'] = (assists / turnovers) if turnovers > 0 else (assists if assists > 0 else 0)
        
        return raw_stats
    
    # Получаем названия команд
    all_teams = league_meta.get_teams()
    team_names = {team.team_id: team.team_name for team in all_teams}
    
    # Рассчитываем для каждой команды
    teams_results = []
    
    for trade in request.trades:
        team_id = trade.team_id
        team_name = team_names.get(team_id, f"Team {team_id}")
        
        # Получаем игроков команды ДО трейда
        team_players_before = [p for p in data['players'] if p['team_id'] == team_id]
        
        # Рассчитываем ДО
        before_z = calculate_total_z(team_players_before, request.punt_categories)
        before_cats = calculate_category_z(team_players_before, request.punt_categories)
        before_raw = calculate_raw_stats(team_players_before, request.punt_categories)
        
        # Формируем состав ПОСЛЕ трейда
        # Убираем игроков, которых отдаем
        team_players_after = [p for p in team_players_before if p['name'] not in trade.give]
        
        # Добавляем игроков, которых получаем
        players_received = [p for p in data['players'] if p['name'] in trade.receive]
        team_players_after.extend(players_received)
        
        # Рассчитываем ПОСЛЕ
        after_z = calculate_total_z(team_players_after, request.punt_categories)
        after_cats = calculate_category_z(team_players_after, request.punt_categories)
        after_raw = calculate_raw_stats(team_players_after, request.punt_categories)
        
        # Формируем данные по категориям
        categories = {}
        raw_categories = {}
        for cat in CATEGORIES:
            if cat not in request.punt_categories:
                before_val = before_cats.get(cat, 0)
                after_val = after_cats.get(cat, 0)
                categories[cat] = {
                    "before": round(before_val, 2),
                    "after": round(after_val, 2),
                    "delta": round(after_val - before_val, 2)
                }
                
                before_raw_val = before_raw.get(cat, 0)
                after_raw_val = after_raw.get(cat, 0)
                raw_categories[cat] = {
                    "before": round(before_raw_val, 2),
                    "after": round(after_raw_val, 2),
                    "delta": round(after_raw_val - before_raw_val, 2)
                }
        
        teams_results.append({
            "team_id": team_id,
            "team_name": team_name,
            "before_z": round(before_z, 2),
            "after_z": round(after_z, 2),
            "delta": round(after_z - before_z, 2),
            "categories": categories,
            "raw_categories": raw_categories,
            "players_given": trade.give,
            "players_received": trade.receive
        })
    
    # Симуляция мест (аналогично analyze_trade)
    # Создаем списки игроков ДО и ПОСЛЕ трейда
    all_players_before = []
    for player in data['players']:
        all_players_before.append(player.copy())
    
    all_players_after = []
    for player in data['players']:
        player_copy = player.copy()
        # Применяем перемещения
        if player['name'] in player_movements:
            player_copy['team_id'] = player_movements[player['name']]
            player_copy['team_name'] = team_names.get(player_movements[player['name']], f"Team {player_movements[player['name']]}")
        all_players_after.append(player_copy)
    
    # Функция расчета мест (использует тот же метод, что и /api/simulation - head-to-head)
    def calculate_simulation_ranks(all_players_list, mode_type):
        from core.config import CATEGORIES
        teams = league_meta.get_teams()
        team_stats = {}
        
        if mode_type == 'z_scores':
            # Режим по Z-score (как в /api/simulation mode="z_scores")
            # Получаем Z-scores для всех игроков
            z_data = calculate_z_scores(league_meta, request.period, exclude_ir=request.exclude_ir)
            
            # Создаем словарь для быстрого поиска Z-scores по имени
            z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
            
            # Группируем игроков по командам (с учетом перемещений из all_players_list)
            players_by_team = {}
            for player in all_players_list:
                team_id = player['team_id']
                if team_id not in players_by_team:
                    players_by_team[team_id] = []
                # Получаем Z-scores для этого игрока
                player_z = z_scores_by_name.get(player['name'], {})
                players_by_team[team_id].append({
                    'name': player['name'],
                    'z_scores': player_z
                })
            
            # Рассчитываем Z по категориям для каждой команды
            def calculate_team_category_z(team_players):
                cat_totals = {cat: 0 for cat in CATEGORIES}
                for player in team_players:
                    for cat in CATEGORIES:
                        if cat not in request.punt_categories:
                            z_val = player['z_scores'].get(cat, 0)
                            if math.isfinite(z_val):
                                cat_totals[cat] += z_val
                return cat_totals
            
            for team in teams:
                if team.team_id in players_by_team:
                    team_players = players_by_team[team.team_id]
                    team_cats = calculate_team_category_z(team_players)
                    team_stats[team.team_id] = {
                        'name': team.team_name,
                        'stats': team_cats
                    }
                else:
                    # Команда без игроков
                    team_stats[team.team_id] = {
                        'name': team.team_name,
                        'stats': {cat: 0.0 for cat in CATEGORIES}
                    }
                    
        elif mode_type == 'team_stats_avg':
            # Режим по статистике команд (avg) - как в /api/simulation mode="team_stats_avg"
            all_players_week_stats = league_meta.get_all_players_stats(request.period, 'avg', exclude_ir=request.exclude_ir)
            
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
                    team_raw_stats = calculate_raw_stats(team_players, request.punt_categories)
                    
                    # Преобразуем в формат для сравнения (только нужные категории)
                    filtered_stats = {}
                    for cat in CATEGORIES:
                        if cat not in request.punt_categories:
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
        
        # Симуляция "все против всех" (как в /api/simulation)
        if not team_stats:
            return {}
        
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
                    if cat in request.punt_categories:
                        continue  # Пропускаем punt категории
                    
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
        
        # Формируем итоговый список с винрейтом (как в обычном трейде)
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
                'win_rate': win_rate
            })
        
        # Сортируем по винрейту (как в обычном трейде и /api/simulation)
        final_results.sort(key=lambda x: x['win_rate'], reverse=True)
        
        # Создаем словарь мест
        ranks = {}
        for rank, team_result in enumerate(final_results, 1):
            ranks[team_result['team_id']] = rank
        
        return ranks
    
    ranks_before_z = calculate_simulation_ranks(all_players_before, 'z_scores')
    ranks_after_z = calculate_simulation_ranks(all_players_after, 'z_scores')
    ranks_before_avg = calculate_simulation_ranks(all_players_before, 'team_stats_avg')
    ranks_after_avg = calculate_simulation_ranks(all_players_after, 'team_stats_avg')
    
    # Формируем данные о местах для каждой команды
    simulation_ranks = {
        'z_scores': {},
        'team_stats_avg': {}
    }
    
    for trade in request.trades:
        team_id = trade.team_id
        simulation_ranks['z_scores'][team_id] = {
            'before': ranks_before_z.get(team_id),
            'after': ranks_after_z.get(team_id),
            'delta': (ranks_after_z.get(team_id, 0) - ranks_before_z.get(team_id, 0)) if (team_id in ranks_after_z and team_id in ranks_before_z) else None
        }
        simulation_ranks['team_stats_avg'][team_id] = {
            'before': ranks_before_avg.get(team_id),
            'after': ranks_after_avg.get(team_id),
            'delta': (ranks_after_avg.get(team_id, 0) - ranks_before_avg.get(team_id, 0)) if (team_id in ranks_after_avg and team_id in ranks_before_avg) else None
        }
    
    return {
        "teams": teams_results,
        "simulation_ranks": simulation_ranks,
        "validation": {
            "is_valid": True,
            "errors": []
        }
    }

@app.get("/api/dashboard/{team_id}")
def get_dashboard(team_id: int, period: str = "2026_total", exclude_ir: bool = False):
    """
    Получает данные для дашборда команды:
    - Информация о команде
    - Текущий матчап
    - Топ-3 игрока
    - Список травмированных игроков
    """
    from core.z_score import calculate_z_scores
    import math
    
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

@app.get("/api/dashboard/{team_id}/matchup-details")
def get_matchup_details(team_id: int, week: int = None):
    """
    Получает детальную информацию о матчапе команды.
    Возвращает сравнение статистики по всем категориям.
    
    Args:
        team_id: ID команды
        week: Номер недели (если не указан, используется текущая неделя)
    """
    from core.config import CATEGORIES
    
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

@app.get("/api/dashboard/{team_id}/matchup-history")
def get_matchup_history(team_id: int):
    """
    Получает историю всех матчапов команды за все недели.
    Возвращает список матчапов с результатами.
    """
    from core.config import CATEGORIES
    
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

@app.get("/api/player/{player_name}/trends")
def get_player_trends(player_name: str):
    """
    Получает тренды игрока на основе доступных периодов.
    Использует периоды: last_7, last_15, last_30, total для показа изменения статистики.
    """
    from core.z_score import calculate_z_scores
    from core.config import CATEGORIES
    import math
    
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
            from core.z_score import COUNTING_CATEGORIES, PERCENTAGE_CATEGORIES
            
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

@app.get("/api/player/{player_name}/balance")
def get_player_balance(player_name: str, period: str = "2026_total"):
    """
    Получает данные для радар-графика баланса игрока.
    Возвращает Z-scores по категориям.
    """
    from core.z_score import calculate_z_scores
    from core.config import CATEGORIES
    import math
    
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
        from core.z_score import COUNTING_CATEGORIES, PERCENTAGE_CATEGORIES
        
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

@app.get("/api/team-balance/{team_id}")
def get_team_balance(team_id: int, period: str = "2026_total", punt_categories: str = "", exclude_ir: bool = False):
    """
    Получает данные для радар-графика баланса команды.
    Возвращает Z-scores по категориям.
    """
    from core.z_score import calculate_z_scores
    from core.config import CATEGORIES
    import math
    
    # Парсим punt категории
    punt_cats = []
    if punt_categories:
        punt_cats = punt_categories.split(',')
    
    # Рассчитываем Z-scores для всей лиги
    data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
    
    if not data['players']:
        return {"error": "No data found"}
    
    # Фильтруем данные только для выбранной команды
    team_players = [p for p in data['players'] if p['team_id'] == team_id]
    
    if not team_players:
        return {"error": "Team not found"}
    
    # Получаем название команды
    team = league_meta.get_team_by_id(team_id)
    team_name = team.team_name if team else f"Team {team_id}"
    
    # Суммируем Z-scores по категориям
    category_totals = {cat: 0 for cat in CATEGORIES}
    
    for player in team_players:
        for cat in CATEGORIES:
            if cat not in punt_cats:
                z_val = player['z_scores'].get(cat, 0)
                if math.isfinite(z_val):
                    category_totals[cat] += z_val
    
    # Форматируем для Recharts
    radar_data = []
    for cat in CATEGORIES:
        if cat not in punt_cats:
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

@app.get("/api/simulation-detailed/{week}")
def get_simulation_detailed(week: int, weeks_count: int = None, mode: str = "matchup", period: str = "2026_total", exclude_ir: bool = False):
    """
    Расширенная симуляция с детальными результатами матчапов для каждой команды.
    """
    from core.config import CATEGORIES
    from core.z_score import calculate_z_scores
    import math
    
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
        all_players = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        def calculate_team_raw_stats(team_players):
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
                
                for cat in counting_stats:
                    val = stats.get(cat, 0)
                    counting_stats[cat] += val if math.isfinite(val) else 0
                
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
            
            raw_stats = counting_stats.copy()
            raw_stats['FG%'] = (fg_makes / fg_attempts * 100) if fg_attempts > 0 else 0
            raw_stats['FT%'] = (ft_makes / ft_attempts * 100) if ft_attempts > 0 else 0
            raw_stats['3PT%'] = (three_makes / three_attempts * 100) if three_attempts > 0 else 0
            raw_stats['A/TO'] = (assists / turnovers) if turnovers > 0 else (assists if assists > 0 else 0)
            
            return raw_stats
        
        players_by_team = {}
        for player in all_players:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
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
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        
        if not z_data['players']:
            return {"error": "No data found"}
        
        def calculate_team_category_z(team_players):
            cat_totals = {cat: 0 for cat in CATEGORIES}
            for player in team_players:
                for cat in CATEGORIES:
                    z_val = player['z_scores'].get(cat, 0)
                    if math.isfinite(z_val):
                        cat_totals[cat] += z_val
            return cat_totals
        
        players_by_team = {}
        for player in z_data['players']:
            team_id = player['team_id']
            if team_id not in players_by_team:
                players_by_team[team_id] = []
            players_by_team[team_id].append(player)
        
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
