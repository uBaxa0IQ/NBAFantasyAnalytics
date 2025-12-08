"""
Роутер для работы с командами и лигой.
"""
from fastapi import APIRouter, Depends
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
import math

router = APIRouter(prefix="/api", tags=["teams"])


@router.get("/teams")
def get_teams(league_meta=Depends(get_league_meta)):
    """Получает список всех команд лиги."""
    teams = league_meta.get_teams()
    return [{"team_id": t.team_id, "team_name": t.team_name} for t in teams]


@router.post("/refresh-league")
def refresh_league(league_meta=Depends(get_league_meta)):
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


@router.get("/weeks")
def get_weeks(league_meta=Depends(get_league_meta)):
    """Получает список всех недель и текущую неделю."""
    weeks = list(range(1, league_meta.league.currentMatchupPeriod + 1))
    return {
        "weeks": weeks,
        "current_week": league_meta.league.currentMatchupPeriod
    }


@router.get("/refresh-status")
def get_refresh_status(league_meta=Depends(get_league_meta)):
    """
    Получает информацию о последнем обновлении данных лиги.
    
    Returns:
        Словарь с информацией об обновлении:
        {
            "last_refresh_time": str (ISO формат) или null,
            "auto_refresh_enabled": bool
        }
    """
    last_refresh = league_meta.get_last_refresh_time()
    return {
        "last_refresh_time": last_refresh.isoformat() if last_refresh else None,
        "auto_refresh_enabled": True,
        "refresh_interval_minutes": 5
    }


@router.get("/generate-prompt")
def generate_llm_prompt(
    period: str = "2026_total",
    exclude_ir: bool = False,
    league_meta=Depends(get_league_meta)
):
    """
    Генерирует промпт с полным контекстом лиги для использования в LLM (ChatGPT, Claude и т.д.).
    
    Args:
        period: Период статистики
        exclude_ir: Исключить IR игроков
    
    Returns:
        Промпт в виде строки с полным контекстом лиги
    """
    try:
        # Получаем информацию о лиге
        league = league_meta.league
        current_week = league.currentMatchupPeriod
        
        # Получаем все команды
        teams = league_meta.get_teams()
        teams_data = []
        for team in teams:
            teams_data.append({
                "team_id": team.team_id,
                "team_name": team.team_name
            })
        
        # Рассчитываем Z-scores для всех игроков
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        
        # Получаем полную статистику всех игроков
        all_players_with_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        stats_by_name = {p['name']: p['stats'] for p in all_players_with_stats}
        
        # Формируем данные по командам с игроками
        teams_with_players = {}
        for player in z_data['players']:
            team_id = player['team_id']
            if team_id not in teams_with_players:
                teams_with_players[team_id] = {
                    "team_id": team_id,
                    "team_name": player['team_name'],
                    "players": []
                }
            
            # Получаем статистику игрока
            player_stats = stats_by_name.get(player['name'], {})
            
            # Очищаем z_scores от inf/nan
            clean_z_scores = {}
            for cat, val in player.get('z_scores', {}).items():
                if isinstance(val, (int, float)) and math.isfinite(val):
                    clean_z_scores[cat] = round(val, 2)
                else:
                    clean_z_scores[cat] = 0.0
            
            # Очищаем stats от inf/nan
            clean_stats = {}
            if player_stats:
                for key, val in player_stats.items():
                    if isinstance(val, float) and math.isfinite(val):
                        clean_stats[key] = round(val, 2) if isinstance(val, float) else val
                    elif isinstance(val, (int, float)):
                        clean_stats[key] = 0.0
                    else:
                        clean_stats[key] = val
            
            teams_with_players[team_id]["players"].append({
                "name": player['name'],
                "position": player.get('position', 'N/A'),
                "z_scores": clean_z_scores,
                "stats": clean_stats
            })
        
        # Формируем промпт
        prompt = f"""Ты - эксперт по анализу Fantasy NBA лиги. Ниже представлен полный контекст лиги для анализа.

# Информация о лиге
- Текущая неделя: {current_week}
- Период статистики: {period}
- Количество команд: {len(teams_data)}
- Метрики лиги: {z_data.get('league_metrics', {})}

# Команды лиги
"""
        
        for team_data in teams_with_players.values():
            prompt += f"\n## {team_data['team_name']} (ID: {team_data['team_id']})\n"
            prompt += f"Игроков: {len(team_data['players'])}\n\n"
            
            # Сортируем игроков по общему Z-score
            players_sorted = sorted(
                team_data['players'],
                key=lambda p: sum(p['z_scores'].values()),
                reverse=True
            )
            
            for player in players_sorted:
                total_z = sum(player['z_scores'].values())
                prompt += f"### {player['name']} ({player['position']})\n"
                prompt += f"Общий Z-score: {round(total_z, 2)}\n"
                prompt += f"Z-scores по категориям: {player['z_scores']}\n"
                if player['stats']:
                    prompt += f"Статистика: {player['stats']}\n"
                prompt += "\n"
        
        prompt += """
# Инструкции для анализа
Используй эту информацию для:
- Анализа сильных и слабых сторон команд
- Рекомендаций по трейдам
- Оценки ценности игроков
- Стратегических советов по управлению ростером
- Анализа матчапов

Будь конкретным и используй данные Z-scores и статистику для обоснования своих рекомендаций.
"""
        
        return {
            "prompt": prompt,
            "period": period,
            "current_week": current_week,
            "teams_count": len(teams_data),
            "players_count": len(z_data['players'])
        }
    
    except Exception as e:
        return {
            "error": f"Ошибка при генерации промпта: {str(e)}"
        }


@router.get("/teams/{team_id}/players-for-selection")
def get_players_for_selection(
    team_id: int,
    period: str = "2026_total",
    league_meta=Depends(get_league_meta)
):
    """
    Получает список всех игроков команды (включая IR) с их Z-scores,
    отсортированных по total Z-score.
    
    Args:
        team_id: ID команды
        period: Период статистики
    
    Returns:
        Список игроков с их Z-scores, отсортированных по total Z-score
    """
    # Получаем команду
    team = league_meta.get_team_by_id(team_id)
    if not team:
        return {"error": "Team not found"}
    
    # Получаем ростер команды (включая IR)
    roster = league_meta.get_team_roster(team_id)
    
    # Получаем Z-scores для всех игроков (включая IR)
    z_data = calculate_z_scores(league_meta, period, exclude_ir=False)
    
    if not z_data['players']:
        return {"error": "No data found"}
    
    # Создаем словарь Z-scores по имени игрока
    z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
    
    # Формируем список игроков с их Z-scores
    players_list = []
    for player in roster:
        player_name = player.name
        z_scores = z_scores_by_name.get(player_name, {})
        
        # Рассчитываем total Z-score
        total_z = 0
        for cat, z_val in z_scores.items():
            if isinstance(z_val, (int, float)) and math.isfinite(z_val):
                total_z += z_val
        
        # Проверяем, находится ли игрок в IR
        lineup_slot = getattr(player, 'lineupSlot', '')
        is_ir = (lineup_slot == 'IR')
        
        players_list.append({
            'name': player_name,
            'position': getattr(player, 'position', 'N/A'),
            'z_scores': z_scores,
            'total_z': round(total_z, 2),
            'is_ir': is_ir
        })
    
    # Сортируем по total Z-score (по убыванию)
    players_list.sort(key=lambda x: x['total_z'], reverse=True)
    
    return {
        'team_id': team_id,
        'team_name': team.team_name,
        'players': players_list
    }
