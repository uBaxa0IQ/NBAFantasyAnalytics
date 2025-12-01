"""
Роутер для анализа трейдов.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from models import TradeAnalysisRequest, MultiTeamTradeRequest
from core.z_score import calculate_z_scores
from core.config import CATEGORIES
from utils.calculations import (
    calculate_total_z,
    calculate_category_z,
    calculate_raw_stats,
    calculate_simulation_ranks,
    calculate_category_rankings
)
import math

router = APIRouter(prefix="/api", tags=["trades"])


@router.post("/trade-analysis")
def analyze_trade(
    request: TradeAnalysisRequest,
    league_meta=Depends(get_league_meta)
):
    """Анализирует трейд между двумя командами."""
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
    ranks_before_z = calculate_simulation_ranks(
        all_players_before, 'z_scores', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_after_z = calculate_simulation_ranks(
        all_players_after, 'z_scores', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_before_avg = calculate_simulation_ranks(
        all_players_before, 'team_stats_avg', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_after_avg = calculate_simulation_ranks(
        all_players_after, 'team_stats_avg', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    
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
    
    # Рассчитываем позиции по категориям ДО и ПОСЛЕ трейда
    category_rankings_before = calculate_category_rankings(
        all_players_before, request.my_team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    category_rankings_after = calculate_category_rankings(
        all_players_after, request.my_team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    
    their_category_rankings_before = calculate_category_rankings(
        all_players_before, request.their_team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    their_category_rankings_after = calculate_category_rankings(
        all_players_after, request.their_team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    
    # Формируем данные о позициях по категориям
    my_category_rankings = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            before_rank = category_rankings_before.get(cat)
            after_rank = category_rankings_after.get(cat)
            if before_rank is not None and after_rank is not None:
                my_category_rankings[cat] = {
                    'before': before_rank,
                    'after': after_rank,
                    'delta': after_rank - before_rank
                }
    
    their_category_rankings = {}
    for cat in CATEGORIES:
        if cat not in request.punt_categories:
            before_rank = their_category_rankings_before.get(cat)
            after_rank = their_category_rankings_after.get(cat)
            if before_rank is not None and after_rank is not None:
                their_category_rankings[cat] = {
                    'before': before_rank,
                    'after': after_rank,
                    'delta': after_rank - before_rank
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
        "simulation_ranks": simulation_ranks,
        "category_rankings": {
            "my_team": my_category_rankings,
            "their_team": their_category_rankings
        }
    }


@router.post("/multi-team-trade-analysis")
def analyze_multi_team_trade(
    request: MultiTeamTradeRequest,
    league_meta=Depends(get_league_meta)
):
    """
    Анализ мультикомандного трейда.
    Поддерживает любое количество команд, участвующих в трейде.
    """
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
    
    ranks_before_z = calculate_simulation_ranks(
        all_players_before, 'z_scores', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_after_z = calculate_simulation_ranks(
        all_players_after, 'z_scores', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_before_avg = calculate_simulation_ranks(
        all_players_before, 'team_stats_avg', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    ranks_after_avg = calculate_simulation_ranks(
        all_players_after, 'team_stats_avg', league_meta, request.period, request.exclude_ir, request.punt_categories
    )
    
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
    
    # Рассчитываем позиции по категориям для каждой команды ДО и ПОСЛЕ трейда
    category_rankings = {}
    for trade in request.trades:
        team_id = trade.team_id
        category_rankings_before = calculate_category_rankings(
            all_players_before, team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
        )
        category_rankings_after = calculate_category_rankings(
            all_players_after, team_id, league_meta, request.period, request.exclude_ir, request.punt_categories
        )
        
        # Формируем данные о позициях по категориям
        team_category_rankings = {}
        for cat in CATEGORIES:
            if cat not in request.punt_categories:
                before_rank = category_rankings_before.get(cat)
                after_rank = category_rankings_after.get(cat)
                if before_rank is not None and after_rank is not None:
                    team_category_rankings[cat] = {
                        'before': before_rank,
                        'after': after_rank,
                        'delta': after_rank - before_rank
                    }
        
        category_rankings[team_id] = team_category_rankings
    
    return {
        "teams": teams_results,
        "simulation_ranks": simulation_ranks,
        "category_rankings": category_rankings,
        "validation": {
            "is_valid": True,
            "errors": []
        }
    }

