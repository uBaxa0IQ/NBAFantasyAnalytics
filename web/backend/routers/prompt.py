"""
Роутер для генерации промпта с контекстом для LLM.
"""
from fastapi import APIRouter, Depends, Query
from dependencies import get_league_meta
from core.z_score import calculate_z_scores
from core.config import CATEGORIES, LEAGUE_ID, YEAR
from utils.calculations import calculate_team_raw_stats, select_top_n_players
from typing import Optional
import json
import math
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api", tags=["prompt"])


def clean_for_json(obj):
    """
    Рекурсивно очищает объект от inf, -inf и nan значений для JSON сериализации.
    """
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return 0.0
        return obj
    elif isinstance(obj, dict):
        return {key: clean_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(item) for item in obj]
    else:
        return obj


def format_value(value):
    """Форматирует значение для Markdown таблицы."""
    if isinstance(value, float):
        if math.isinf(value) or math.isnan(value):
            return "0.0"
        formatted = f"{value:.2f}".rstrip('0').rstrip('.')
        return formatted if formatted else "0.0"
    elif isinstance(value, int):
        return str(value)
    elif value is None:
        return "N/A"
    elif isinstance(value, str):
        return value
    else:
        return str(value)


def generate_markdown_table(headers, rows):
    """Генерирует Markdown таблицу."""
    if not rows:
        return ""
    
    # Формируем заголовки
    header_row = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    
    # Формируем строки данных
    data_rows = []
    for row in rows:
        formatted_row = [format_value(cell) for cell in row]
        data_rows.append("| " + " | ".join(formatted_row) + " |")
    
    return "\n".join([header_row, separator] + data_rows)


def generate_markdown_prompt(full_data: dict) -> str:
    """Генерирует промпт в формате Markdown с таблицами."""
    md_lines = []
    
    # 1. League Info
    li = full_data.get("li", {})
    md_lines.append("## League Information")
    md_lines.append(f"- **League ID**: {li.get('lid', 'N/A')}")
    md_lines.append(f"- **Season**: {li.get('y', 'N/A')}")
    md_lines.append(f"- **Current Week**: {li.get('cw', 'N/A')}")
    md_lines.append(f"- **Total Teams**: {li.get('tt', 'N/A')}")
    md_lines.append(f"- **Categories**: {', '.join(li.get('cats', []))}")
    if li.get('lrt'):
        md_lines.append(f"- **Last Refresh**: {li.get('lrt')}")
    md_lines.append("")
    
    # 2. Settings
    s = full_data.get("s", {})
    md_lines.append("## Settings")
    md_lines.append(f"- **Period**: {s.get('p', 'N/A')}")
    md_lines.append(f"- **Simulation Mode**: {s.get('sm', 'N/A')}")
    md_lines.append(f"- **Top N Players**: {s.get('tn', 'N/A')}")
    if s.get('mt'):
        md_lines.append(f"- **Main Team**: {s.get('mtn', 'N/A')} (ID: {s.get('mt')})")
    if s.get('pc'):
        md_lines.append(f"- **Punt Categories**: {', '.join(s.get('pc', []))}")
    if s.get('ctp'):
        md_lines.append(f"- **Custom Team Players**: {', '.join(s.get('ctp', []))}")
    md_lines.append("")
    
    # 3. Teams
    teams = full_data.get("t", [])
    if teams:
        md_lines.append("## Teams")
        headers = ["ID", "Name", "Wins", "Losses", "Ties", "Win Rate", "Position", "Roster Size", "Healthy Players", "Current Matchup"]
        rows = []
        for team in teams:
            matchup = team.get('m', {})
            matchup_str = f"{matchup.get('on', 'N/A')}" if matchup else "N/A"
            rows.append([
                team.get('id', 'N/A'),
                team.get('n', 'N/A'),
                team.get('w', 0),
                team.get('l', 0),
                team.get('t', 0),
                team.get('wr', 0.0),
                team.get('pos', 'N/A'),
                team.get('rs', 0),
                team.get('hp', 0),
                matchup_str
            ])
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append("")
    
    # 4. Players
    players = full_data.get("p", [])
    if players:
        md_lines.append("## Players")
        cats = li.get('cats', CATEGORIES)
        headers = ["Name", "Pos", "NBA Team", "Fantasy Team", "Team ID"] + cats + ["Total Z", "Total Z Punt", "GP", "Injured", "IR"]
        rows = []
        for player in players[:200]:  # Ограничиваем для читаемости
            stats = player.get('s', [])
            z_scores = player.get('z', [])
            
            # Если compact формат - это массивы, иначе словари
            if isinstance(stats, list):
                stats_row = stats[:len(cats)]
            else:
                stats_row = [stats.get(cat, 0.0) for cat in cats]
            
            if isinstance(z_scores, list):
                z_row = z_scores[:len(cats)]
            else:
                z_row = [z_scores.get(cat, 0.0) for cat in cats]
            
            # Объединяем stats и z_scores в одну строку для компактности
            combined_stats = []
            for i, cat in enumerate(cats):
                stat_val = stats_row[i] if i < len(stats_row) else 0.0
                z_val = z_row[i] if i < len(z_row) else 0.0
                # Обрабатываем случаи, когда значения могут быть не числами
                try:
                    stat_val = float(stat_val) if stat_val is not None else 0.0
                    z_val = float(z_val) if z_val is not None else 0.0
                    if math.isinf(stat_val) or math.isnan(stat_val):
                        stat_val = 0.0
                    if math.isinf(z_val) or math.isnan(z_val):
                        z_val = 0.0
                    combined_stats.append(f"{stat_val:.2f} (z:{z_val:.2f})")
                except (ValueError, TypeError):
                    combined_stats.append("0.0 (z:0.0)")
            
            rows.append([
                player.get('n', 'N/A'),
                player.get('pos', 'N/A'),
                player.get('nba', 'N/A'),
                player.get('t', 'N/A'),
                player.get('tid', 'N/A'),
            ] + combined_stats + [
                player.get('tz', 0.0),
                player.get('tzp', 0.0),
                player.get('gp', 0),
                "Yes" if player.get('inj', False) else "No",
                "Yes" if player.get('ir', False) else "No"
            ])
        
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append(f"\n*Showing {min(len(players), 200)} of {len(players)} players*")
        md_lines.append("")
    
    # 5. Free Agents
    fa = full_data.get("fa", [])
    if fa:
        md_lines.append("## Free Agents (Top 50)")
        cats = li.get('cats', CATEGORIES)
        headers = ["Name", "Pos", "NBA Team"] + cats + ["Total Z", "Total Z Punt", "GP"]
        rows = []
        for agent in fa[:50]:
            stats = agent.get('s', [])
            z_scores = agent.get('z', [])
            
            if isinstance(stats, list):
                stats_row = stats[:len(cats)]
            else:
                stats_row = [stats.get(cat, 0.0) for cat in cats]
            
            if isinstance(z_scores, list):
                z_row = z_scores[:len(cats)]
            else:
                z_row = [z_scores.get(cat, 0.0) for cat in cats]
            
            combined_stats = []
            for i, cat in enumerate(cats):
                stat_val = stats_row[i] if i < len(stats_row) else 0.0
                z_val = z_row[i] if i < len(z_row) else 0.0
                # Обрабатываем случаи, когда значения могут быть не числами
                try:
                    stat_val = float(stat_val) if stat_val is not None else 0.0
                    z_val = float(z_val) if z_val is not None else 0.0
                    if math.isinf(stat_val) or math.isnan(stat_val):
                        stat_val = 0.0
                    if math.isinf(z_val) or math.isnan(z_val):
                        z_val = 0.0
                    combined_stats.append(f"{stat_val:.2f} (z:{z_val:.2f})")
                except (ValueError, TypeError):
                    combined_stats.append("0.0 (z:0.0)")
            
            rows.append([
                agent.get('n', 'N/A'),
                agent.get('pos', 'N/A'),
                agent.get('nba', 'N/A'),
            ] + combined_stats + [
                agent.get('tz', 0.0),
                agent.get('tzp', 0.0),
                agent.get('gp', 0)
            ])
        
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append("")
    
    # 6. Simulations
    sim = full_data.get("sim", {})
    if sim:
        md_lines.append("## Simulations")
        
        # Функция для получения названия периода
        def get_period_name(period_key):
            period_names = {
                '2026_total': 'Total Season',
                '2026_last_30': 'Last 30 Days',
                '2026_last_15': 'Last 15 Days',
                '2026_last_7': 'Last 7 Days',
                '2026_weighted': 'Weighted (Universal)'
            }
            return period_names.get(period_key, period_key)
        
        # Симуляции по avg
        sim_avg_selected = sim.get('by_avg_selected', {})
        sim_avg_total = sim.get('by_avg_total', {})
        sim_z_selected = sim.get('by_z_score_selected', {})
        sim_z_total = sim.get('by_z_score_total', {})
        
        # Выбранный период (основной)
        if sim_avg_selected and sim_avg_selected.get('r'):
            period_name = get_period_name(sim_avg_selected.get('p', ''))
            md_lines.append(f"### Simulation by Average Stats - {period_name}")
            headers = ["Pos", "Team ID", "Team Name", "Wins", "Losses", "Ties", "Win Rate"]
            rows = []
            for result in sim_avg_selected['r']:
                rows.append([
                    result.get('pos', 'N/A'),
                    result.get('id', 'N/A'),
                    result.get('n', 'N/A'),
                    result.get('w', 0),
                    result.get('l', 0),
                    result.get('t', 0),
                    result.get('wr', 0.0)
                ])
            md_lines.append(generate_markdown_table(headers, rows))
            md_lines.append("")
        
        # Total для сравнения
        if sim_avg_total and sim_avg_total.get('r'):
            md_lines.append("### Simulation by Average Stats - Total Season (for comparison)")
            headers = ["Pos", "Team ID", "Team Name", "Wins", "Losses", "Ties", "Win Rate"]
            rows = []
            for result in sim_avg_total['r']:
                rows.append([
                    result.get('pos', 'N/A'),
                    result.get('id', 'N/A'),
                    result.get('n', 'N/A'),
                    result.get('w', 0),
                    result.get('l', 0),
                    result.get('t', 0),
                    result.get('wr', 0.0)
                ])
            md_lines.append(generate_markdown_table(headers, rows))
            md_lines.append("")
        
        # Выбранный период по Z-Score
        if sim_z_selected and sim_z_selected.get('r'):
            period_name = get_period_name(sim_z_selected.get('p', ''))
            md_lines.append(f"### Simulation by Z-Score - {period_name}")
            headers = ["Pos", "Team ID", "Team Name", "Wins", "Losses", "Ties", "Win Rate"]
            rows = []
            for result in sim_z_selected['r']:
                rows.append([
                    result.get('pos', 'N/A'),
                    result.get('id', 'N/A'),
                    result.get('n', 'N/A'),
                    result.get('w', 0),
                    result.get('l', 0),
                    result.get('t', 0),
                    result.get('wr', 0.0)
                ])
            md_lines.append(generate_markdown_table(headers, rows))
            md_lines.append("")
        
        # Total по Z-Score для сравнения
        if sim_z_total and sim_z_total.get('r'):
            md_lines.append("### Simulation by Z-Score - Total Season (for comparison)")
            headers = ["Pos", "Team ID", "Team Name", "Wins", "Losses", "Ties", "Win Rate"]
            rows = []
            for result in sim_z_total['r']:
                rows.append([
                    result.get('pos', 'N/A'),
                    result.get('id', 'N/A'),
                    result.get('n', 'N/A'),
                    result.get('w', 0),
                    result.get('l', 0),
                    result.get('t', 0),
                    result.get('wr', 0.0)
                ])
            md_lines.append(generate_markdown_table(headers, rows))
            md_lines.append("")
    
    # 7. Category Rankings
    cr = full_data.get("cr", {})
    if cr:
        md_lines.append("## Category Rankings")
        for cat, teams_list in cr.items():
            if teams_list:
                md_lines.append(f"### {cat}")
                headers = ["Rank", "Team ID", "Team Name", "Value"]
                rows = []
                for team_data in teams_list:
                    if isinstance(team_data, list):
                        rows.append(team_data)
                    else:
                        rows.append([
                            team_data.get('rank', 0),
                            team_data.get('team_id', 0),
                            team_data.get('team_name', 'N/A'),
                            team_data.get('value', 0.0)
                        ])
                md_lines.append(generate_markdown_table(headers, rows))
                md_lines.append("")
    
    # 8. League Metrics
    lm = full_data.get("lm", {})
    if lm:
        md_lines.append("## League Metrics")
        headers = ["Category", "Mean/Avg", "Std"]
        rows = []
        for cat, metrics in lm.items():
            if isinstance(metrics, list):
                if len(metrics) >= 2:
                    rows.append([cat, metrics[0], metrics[1]])
                elif len(metrics) == 3:
                    rows.append([cat, f"{metrics[0]} (impact: {metrics[1]})", metrics[2]])
            else:
                rows.append([cat, metrics.get('mean', 'N/A'), metrics.get('std', 'N/A')])
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append("")
    
    # 9. Matchup History
    mh = full_data.get("mh", [])
    if mh:
        md_lines.append("## Main Team Matchup History")
        headers = ["Week", "Opponent ID", "Opponent Name", "My Wins", "Opponent Wins", "Ties", "Result"]
        rows = []
        for matchup in mh:
            rows.append([
                matchup.get('w', 'N/A'),
                matchup.get('oid', 'N/A'),
                matchup.get('on', 'N/A'),
                matchup.get('mw', 0),
                matchup.get('ow', 0),
                matchup.get('t', 0),
                matchup.get('r', 'N/A')
            ])
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append("")
    
    # 10. Upcoming Matchups
    um = full_data.get("um", [])
    if um:
        md_lines.append("## Upcoming Matchups")
        headers = ["Week", "Team 1 ID", "Team 1 Name", "Team 2 ID", "Team 2 Name"]
        rows = []
        for matchup in um:
            rows.append([
                matchup.get('w', 'N/A'),
                matchup.get('t1', 'N/A'),
                matchup.get('t1n', 'N/A'),
                matchup.get('t2', 'N/A'),
                matchup.get('t2n', 'N/A')
            ])
        md_lines.append(generate_markdown_table(headers, rows))
        md_lines.append("")
    
    return "\n".join(md_lines)


def generate_system_prompt(league_info: dict, settings: dict) -> str:
    """Генерирует системный промпт с подстановкой значений."""
    main_team_line = ""
    if settings.get("mt"):
        main_team_line = f"\n- Основная команда: {settings.get('mtn') or 'N/A'} (id {settings['mt']})"
    custom_players_line = ""
    if settings.get("ctp"):
        custom_players_line = "\n- Кастомный ростер используется для основной команды"
    punt_line = ""
    if settings.get("pc"):
        punt_line = f"\n- Пант категории: {', '.join(settings['pc'])}"
    period_line = f"\n- Период данных: {settings.get('p')}"
    sim_mode_line = f"\n- Режим симуляции: {settings.get('sm')}"
    top_n_line = f"\n- Top-N игроков в расчётах: {settings.get('tn')}"
    refresh_line = ""
    if league_info.get("lrt"):
        refresh_line = f"\n- Последнее обновление данных: {league_info['lrt']}"
    
    return f"""Ты анализируешь NBA Fantasy Basketball лигу ИСКЛЮЧИТЕЛЬНО на основе предоставленной статистики.

ВАЖНО: Используй ТОЛЬКО данные из предоставленных таблиц Markdown. НЕ используй свои знания об игроках, командах или лиге. Все выводы должны основываться исключительно на предоставленных цифрах из таблиц.

ЛИГА:
- Лига #{league_info['lid']}, сезон {league_info['y']}, неделя {league_info['cw']}, {league_info['tt']} команд
- Формат: H2H категории; используем категории PTS, REB, AST, STL, BLK, 3PM, DD, FG%, FT%, 3PT%, A/TO
- Порядок категорий фиксирован в массиве cats, все числовые массивы stats/z/tr соответствуют этому порядку
- Числа округлены до 2 знаков (4 для weighted_avg), inf/nan заменены на 0
{period_line}{sim_mode_line}{top_n_line}
- В расчётах на команду берётся максимум 13 играющих (не травмированных/не IR) игроков
- ВАЖНО: Максимум здоровых (не травмированных/не IR) игроков в составе команды = 13
- Если в составе команды больше 13 здоровых игроков, это временная ситуация - главные игроки команды находятся на травме (IR)
{punt_line}{main_team_line}{custom_players_line}{refresh_line}

Z-SCORE:
- Нормализованная метрика: на сколько стандартных отклонений игрок отличается от среднего лиги
- Положительный = выше среднего, отрицательный = ниже, 0 = средний
- Total Z (tz) = сумма Z-scores по всем категориям (без учета пантов)
- Total Z Punt (tzp) = сумма Z-scores с учетом пантов (исключая пант-категории)

ДАННЫЕ В MARKDOWN:
Данные представлены в формате Markdown с таблицами для удобного анализа:
- Команды: таблица с id, названием, рекордами, винрейтом, позицией, размером ростера, количеством здоровых игроков, текущим матчапом
- Игроки: таблица со статистикой (stats) и z-scores по всем категориям, total_z, total_z_punt, games played, статусом травмы/IR, фэнтези-командой
- Свободные агенты: таблица топ-50 с той же структурой данных
- Симуляции: отдельные таблицы для by_avg и by_z_score, каждая для периода "total" (весь сезон) и "last_30" (последние 30 дней)
- Рейтинги по категориям: таблицы команд с rank, team_id, team_name, value для каждой категории
- Метрики лиги: таблица средних значений и стандартных отклонений по категориям
- История матчапов: таблица прошлых матчапов основной команды
- Будущие матчапы: таблица запланированных матчапов

ПРАВИЛА:
1. Анализируй ТОЛЬКО предоставленные цифры
2. Сравнивай игроков по статистике из JSON
3. Выявляй тренды на основе данных tr (тренды по периодам)
4. Используй рейтинги cr для оценки силы команд по категориям
5. НЕ упоминай информацию, которой нет в JSON
6. Все выводы должны быть подкреплены конкретными цифрами из данных
7. Если задана основная команда, делай выводы с акцентом на неё и её матчапы
"""


@router.get("/generate-prompt")
def generate_prompt(
    period: str = Query("2026_total", description="Период статистики"),
    simulation_mode: str = Query("all", description="Режим симуляции"),
    top_n_players: int = Query(13, description="Количество игроков для top_n режима"),
    main_team_id: Optional[int] = Query(None, description="ID основной команды"),
    custom_team_players: Optional[str] = Query(None, description="Список игроков через запятую"),
    punt_categories: Optional[str] = Query(None, description="Категории для исключения через запятую"),
    compact: bool = Query(False, description="Сжимать JSON (меньше форматирования)"),
    league_meta=Depends(get_league_meta)
):
    """
    Генерирует полный промпт с контекстом для LLM в формате JSON.
    """
    try:
        # 1. Базовая информация о лиге
        current_week = league_meta.league.currentMatchupPeriod
        last_refresh = league_meta.get_last_refresh_time()
        
        league_info = {
            "lid": LEAGUE_ID,  # league_id
            "y": YEAR,  # year
            "tt": len(league_meta.get_teams()),  # total_teams
            "cw": current_week,  # current_week
            "cats": CATEGORIES,  # categories
            "lrt": last_refresh.isoformat() if last_refresh else None  # last_refresh_time
        }
        
        # 2. Информация о командах
        teams = league_meta.get_teams()
        teams_data = []
        for team in teams:
            wins = getattr(team, 'wins', 0)
            losses = getattr(team, 'losses', 0)
            ties = getattr(team, 'ties', 0)
            total_games = wins + losses + ties
            win_rate = (wins + 0.5 * ties) / total_games if total_games > 0 else 0
            
            # Получаем текущий матчап
            current_matchup = None
            matchup_box = league_meta.get_matchup_box_score(current_week, team.team_id)
            if matchup_box:
                current_matchup = {
                    "week": current_week,
                    "opponent_id": matchup_box['opponent_id'],
                    "opponent_name": matchup_box['opponent_name']
                }
            
            matchup_data = None
            if current_matchup:
                matchup_data = {
                    "w": current_matchup["week"],
                    "oid": current_matchup["opponent_id"],
                    "on": current_matchup["opponent_name"]
                }
            
            # Подсчитываем количество здоровых (не травмированных/не IR) игроков
            roster = league_meta.get_team_roster(team.team_id)
            healthy_players_count = 0
            for roster_player in roster:
                lineup_slot = getattr(roster_player, 'lineupSlot', '')
                is_ir = (lineup_slot == 'IR')
                is_injured = getattr(roster_player, 'injured', False)
                if not is_ir and not is_injured:
                    healthy_players_count += 1
            
            teams_data.append({
                "id": team.team_id,
                "n": team.team_name,  # name
                "w": wins,
                "l": losses,
                "t": ties,
                "wr": round(win_rate, 3),  # win_rate
                "rs": len(roster),  # roster_size
                "hp": healthy_players_count,  # healthy_players_count
                "m": matchup_data  # current_matchup
            })
        
        # Сортируем команды по винрейту для определения позиции
        teams_data.sort(key=lambda x: (x['wr'], x['w']), reverse=True)
        for idx, team in enumerate(teams_data):
            team['pos'] = idx + 1  # position
        
        # 3. Парсим пант-категории (нужно для расчета total_z с учетом пантов)
        punt_cats_list = []
        if punt_categories:
            punt_cats_list = [cat.strip() for cat in punt_categories.split(',') if cat.strip()]
        
        # 4. Информация об игроках (все)
        exclude_ir = (simulation_mode == "exclude_ir")
        z_data = calculate_z_scores(league_meta, period, exclude_ir=exclude_ir)
        all_players_stats = league_meta.get_all_players_stats(period, 'avg', exclude_ir=exclude_ir)
        
        # Создаем словарь статистики по имени
        stats_by_name = {p['name']: p['stats'] for p in all_players_stats}
        z_scores_by_name = {p['name']: p['z_scores'] for p in z_data['players']}
        
        players_data = []
        for player in z_data['players']:
            player_name = player['name']
            stats = stats_by_name.get(player_name, {})
            z_scores = player['z_scores']
            
            # Вычисляем total_z и очищаем z_scores от inf/nan
            cleaned_z_scores = {}
            for cat, z_val in z_scores.items():
                if isinstance(z_val, (int, float)):
                    if math.isfinite(z_val):
                        cleaned_z_scores[cat] = round(z_val, 2)
                    else:
                        cleaned_z_scores[cat] = 0.0
                else:
                    cleaned_z_scores[cat] = z_val
            
            # total_z без учета пантов (сумма всех категорий)
            total_z = sum(z for z in cleaned_z_scores.values() if isinstance(z, (int, float)) and math.isfinite(z))
            
            # total_z с учетом пантов (исключая пант-категории)
            total_z_punt = 0
            for cat in CATEGORIES:
                if cat not in punt_cats_list:
                    z_val = cleaned_z_scores.get(cat, 0)
                    if isinstance(z_val, (int, float)) and math.isfinite(z_val):
                        total_z_punt += z_val
            
            # Получаем информацию о травме
            is_injured = False
            injury_status = "ACTIVE"
            is_ir = False
            
            # Ищем игрока в ростерах команд для получения дополнительной информации
            nba_team = 'N/A'
            for team in teams:
                roster = league_meta.get_team_roster(team.team_id)
                for roster_player in roster:
                    if roster_player.name == player_name:
                        is_injured = getattr(roster_player, 'injured', False)
                        injury_status = getattr(roster_player, 'injuryStatus', 'ACTIVE')
                        lineup_slot = getattr(roster_player, 'lineupSlot', '')
                        is_ir = (lineup_slot == 'IR')
                        nba_team = getattr(roster_player, 'proTeam', 'N/A')
                        break
                if nba_team != 'N/A':
                    break
            
            # Очищаем stats от inf/nan и фильтруем только нужные категории
            cleaned_stats = {}
            for cat in CATEGORIES:
                if cat in stats:
                    value = stats[cat]
                    if isinstance(value, float):
                        if math.isfinite(value):
                            cleaned_stats[cat] = round(value, 2)
                        else:
                            cleaned_stats[cat] = 0.0
                    else:
                        cleaned_stats[cat] = value
                else:
                    cleaned_stats[cat] = 0.0
            
            # Получаем количество игр (GP - Games Played)
            games_played = 0
            if 'GP' in stats:
                games_played = int(stats['GP']) if isinstance(stats['GP'], (int, float)) and math.isfinite(stats['GP']) else 0
            
            # Получаем тренды игрока
            player_trends = None
            try:
                from routers.players import get_player_trends
                trends_data = get_player_trends(player_name, league_meta)
                if 'trends' in trends_data:
                    # Сжимаем формат трендов - только ключевые данные
                    trends_compressed = []
                    for trend in trends_data['trends']:
                        # Оставляем только stats и total_z для каждого периода
                        trend_stats = {}
                        for cat in CATEGORIES:
                            if cat in trend.get('stats', {}):
                                val = trend['stats'][cat]
                                if isinstance(val, float) and math.isfinite(val):
                                    trend_stats[cat] = round(val, 2)
                                else:
                                    trend_stats[cat] = 0.0
                            else:
                                trend_stats[cat] = 0.0
                        
                        trend_stats_payload = (
                            [trend_stats[cat] for cat in CATEGORIES]
                            if compact else trend_stats
                        )
                        
                        trends_compressed.append({
                            'p': trend['period_key'],  # Сокращенное название периода
                            's': trend_stats_payload,  # stats
                            'z': round(trend.get('total_z', 0), 2)  # total_z
                        })
                    player_trends = trends_compressed
            except Exception as e:
                pass  # Игнорируем ошибки получения трендов
            
            stats_payload = (
                [cleaned_stats[cat] for cat in CATEGORIES]
                if compact else cleaned_stats
            )
            z_payload = (
                [cleaned_z_scores.get(cat, 0.0) for cat in CATEGORIES]
                if compact else cleaned_z_scores
            )
            
            players_data.append({
                "n": player_name,  # name
                "pos": player.get('position', 'N/A'),  # position
                "nba": nba_team,  # nba_team
                "tid": player['team_id'],  # fantasy_team_id
                "t": player['team_name'],  # fantasy_team_name
                "s": stats_payload,  # stats
                "z": z_payload,  # z_scores
                "tz": round(total_z, 2),  # total_z (без учета пантов)
                "tzp": round(total_z_punt, 2),  # total_z_punt (с учетом пантов)
                "gp": games_played,  # games_played
                "tr": player_trends,  # trends
                "inj": is_injured,  # is_injured
                "ir": is_ir  # is_ir
            })
        
        # 5. Текущие настройки
        
        custom_players_list = None
        custom_team_players_str = custom_team_players  # Сохраняем строку для передачи в функции
        if custom_team_players:
            custom_players_list = [name.strip() for name in custom_team_players.split(',') if name.strip()]
        
        main_team_name = None
        if main_team_id:
            main_team = league_meta.get_team_by_id(main_team_id)
            if main_team:
                main_team_name = main_team.team_name
        
        settings_data = {
            "p": period,  # period
            "pc": punt_cats_list,  # punt_categories
            "sm": simulation_mode,  # simulation_mode
            "tn": top_n_players,  # top_n_players
            "mt": main_team_id,  # main_team_id
            "mtn": main_team_name,  # main_team_name
            "ctp": custom_players_list  # custom_team_players
        }
        
        # 5. История матчапов основной команды (если выбрана)
        matchup_history = []
        if main_team_id:
            for week in range(1, current_week):
                matchup_box = league_meta.get_matchup_box_score(week, main_team_id)
                if not matchup_box:
                    continue
                
                opponent_id = matchup_box['opponent_id']
                matchup_summary = league_meta.get_matchup_summary(week, main_team_id, opponent_id)
                if not matchup_summary:
                    continue
                
                if matchup_summary['team1_id'] == main_team_id:
                    my_wins = matchup_summary['team1_wins']
                    opponent_wins = matchup_summary['team2_wins']
                    ties = matchup_summary['ties']
                else:
                    my_wins = matchup_summary['team2_wins']
                    opponent_wins = matchup_summary['team1_wins']
                    ties = matchup_summary['ties']
                
                result = 'W' if my_wins > opponent_wins else ('L' if opponent_wins > my_wins else 'T')
                
                matchup_history.append({
                    "w": week,  # week
                    "oid": opponent_id,  # opponent_id
                    "on": matchup_box['opponent_name'],  # opponent_name
                    "mw": my_wins,  # my_wins
                    "ow": opponent_wins,  # opponent_wins
                    "t": ties,  # ties
                    "r": result  # result
                })
        
        # 6. Будущие матчапы из расписания
        upcoming_matchups = []
        schedule_path = Path(__file__).parent.parent / "shedule.json"
        if schedule_path.exists():
            try:
                with open(schedule_path, 'r', encoding='utf-8') as f:
                    schedule = json.load(f)
                
                # Создаем маппинг названий к ID
                team_name_to_id = {team.team_name: team.team_id for team in teams}
                
                for week_data in schedule:
                    week_num = week_data['week']
                    if week_num >= current_week:
                        for matchup_str in week_data['matchups']:
                            parts = matchup_str.split(' vs ')
                            if len(parts) == 2:
                                team1_name = parts[0].strip()
                                team2_name = parts[1].strip()
                                team1_id = team_name_to_id.get(team1_name)
                                team2_id = team_name_to_id.get(team2_name)
                                
                                if team1_id and team2_id:
                                    upcoming_matchups.append({
                                        "w": week_num,  # week
                                        "t1": team1_id,  # team1_id
                                        "t1n": team1_name,  # team1_name
                                        "t2": team2_id,  # team2_id
                                        "t2n": team2_name  # team2_name
                                    })
            except Exception as e:
                pass  # Игнорируем ошибки загрузки расписания
        
        # 7. Топ-50 свободных агентов
        free_agents_list = league_meta.get_free_agents(size=50)
        fa_data = []
        
        for fa in free_agents_list:
            stats = league_meta.get_player_stats(fa, period, 'avg')
            if not stats:
                continue
            
            # Рассчитываем Z-scores для FA
            z_scores = {}
            league_metrics = z_data['league_metrics']
            
            # Счетные категории
            for cat in ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD']:
                if cat in stats and cat in league_metrics:
                    value = stats[cat]
                    mean = league_metrics[cat]['mean']
                    std = league_metrics[cat]['std']
                    z_score = (value - mean) / std if std > 0 else 0
                    if math.isfinite(z_score):
                        z_scores[cat] = round(z_score, 2)
                    else:
                        z_scores[cat] = 0.0
            
            # Процентные категории (упрощенный расчет)
            for cat in ['FG%', 'FT%', '3PT%', 'A/TO']:
                if cat in stats and cat in league_metrics:
                    value = stats[cat]
                    if 'weighted_avg' in league_metrics[cat]:
                        mean = league_metrics[cat]['weighted_avg']
                        std = league_metrics[cat].get('impact_std', 0.01)
                        z_score = (value - mean) / std if std > 0 else 0
                        if math.isfinite(z_score):
                            z_scores[cat] = round(z_score, 2)
                        else:
                            z_scores[cat] = 0.0
            
            # total_z без учета пантов (сумма всех категорий)
            total_z = sum(z for z in z_scores.values() if isinstance(z, (int, float)) and math.isfinite(z))
            
            # total_z с учетом пантов (исключая пант-категории)
            total_z_punt = 0
            for cat in CATEGORIES:
                if cat not in punt_cats_list:
                    z_val = z_scores.get(cat, 0)
                    if isinstance(z_val, (int, float)) and math.isfinite(z_val):
                        total_z_punt += z_val
            
            # Очищаем stats от inf/nan и фильтруем только нужные категории
            cleaned_fa_stats = {}
            for cat in CATEGORIES:
                if cat in stats:
                    value = stats[cat]
                    if isinstance(value, float):
                        if math.isfinite(value):
                            cleaned_fa_stats[cat] = round(value, 2)
                        else:
                            cleaned_fa_stats[cat] = 0.0
                    else:
                        cleaned_fa_stats[cat] = value
                else:
                    cleaned_fa_stats[cat] = 0.0
            
            # Получаем количество игр для FA
            fa_games = 0
            if 'GP' in stats:
                fa_games = int(stats['GP']) if isinstance(stats['GP'], (int, float)) and math.isfinite(stats['GP']) else 0
            
            fa_data.append({
                "n": fa.name,  # name
                "pos": getattr(fa, 'position', 'N/A'),  # position
                "nba": getattr(fa, 'proTeam', 'N/A'),  # nba_team
                "s": [cleaned_fa_stats[cat] for cat in CATEGORIES] if compact else cleaned_fa_stats,  # stats
                "z": [z_scores.get(cat, 0.0) for cat in CATEGORIES] if compact else z_scores,  # z_scores
                "tz": round(total_z, 2),  # total_z (без учета пантов)
                "tzp": round(total_z_punt, 2),  # total_z_punt (с учетом пантов)
                "gp": fa_games  # games_played
            })
        
        # Сортируем по total_z
        fa_data.sort(key=lambda x: x['tz'], reverse=True)  # tz = total_z
        
        # 8. Симуляции (по avg и z-score)
        # Используем выбранный период и также total для сравнения
        simulations_data = {
            "by_avg_selected": None,
            "by_avg_total": None,
            "by_z_score_selected": None,
            "by_z_score_total": None
        }
        
        # Периоды для симуляций: выбранный период + total для сравнения
        sim_periods = {
            "selected": period,  # Используем выбранный период (может быть weighted)
            "total": "2026_total"  # Всегда добавляем total для контекста
        }
        
        def process_simulation_result(sim_result, teams_data):
            """Обрабатывает результат симуляции и преобразует в нужный формат."""
            if not isinstance(sim_result, list):
                return []
            
            results = []
            for idx, result in enumerate(sim_result):
                team_id = None
                for team in teams_data:
                    if team['n'] == result['name']:
                        team_id = team['id']
                        break
                
                if team_id:
                    win_rate_val = result.get('win_rate', 0)
                    if isinstance(win_rate_val, (int, float)):
                        if win_rate_val > 1:
                            win_rate_val = win_rate_val / 100
                        if not math.isfinite(win_rate_val):
                            win_rate_val = 0.0
                    
                    results.append({
                        "id": team_id,
                        "n": result['name'],
                        "w": result.get('wins', 0),
                        "l": result.get('losses', 0),
                        "t": result.get('ties', 0),
                        "wr": round(win_rate_val, 3),
                        "pos": idx + 1
                    })
            return results
        
        from routers.simulation import get_simulation
        
        # Симуляция по avg для выбранного периода
        try:
            sim_avg_selected = get_simulation(
                week=current_week,
                mode="team_stats_avg",
                period=sim_periods["selected"],
                simulation_mode=simulation_mode,
                top_n_players=top_n_players,
                custom_team_players=custom_team_players_str,
                custom_team_id=main_team_id,
                league_meta=league_meta
            )
            simulations_data["by_avg_selected"] = {
                "m": "avg",
                "p": sim_periods["selected"],
                "sm": simulation_mode,
                "r": process_simulation_result(sim_avg_selected, teams_data)
            }
        except Exception as e:
            print(f"Error in simulation by_avg_selected ({sim_periods['selected']}): {e}")
            import traceback
            traceback.print_exc()
            simulations_data["by_avg_selected"] = {
                "m": "avg",
                "p": sim_periods["selected"],
                "sm": simulation_mode,
                "r": []
            }
        
        # Симуляция по avg для total (для сравнения)
        try:
            sim_avg_total = get_simulation(
                week=current_week,
                mode="team_stats_avg",
                period=sim_periods["total"],
                simulation_mode=simulation_mode,
                top_n_players=top_n_players,
                custom_team_players=custom_team_players_str,
                custom_team_id=main_team_id,
                league_meta=league_meta
            )
            simulations_data["by_avg_total"] = {
                "m": "avg",
                "p": sim_periods["total"],
                "sm": simulation_mode,
                "r": process_simulation_result(sim_avg_total, teams_data)
            }
        except Exception as e:
            print(f"Error in simulation by_avg_total: {e}")
            import traceback
            traceback.print_exc()
            simulations_data["by_avg_total"] = {
                "m": "avg",
                "p": sim_periods["total"],
                "sm": simulation_mode,
                "r": []
            }
        
        # Симуляция по z-score для выбранного периода
        try:
            sim_z_selected = get_simulation(
                week=current_week,
                mode="z_scores",
                period=sim_periods["selected"],
                simulation_mode=simulation_mode,
                top_n_players=top_n_players,
                custom_team_players=custom_team_players_str,
                custom_team_id=main_team_id,
                league_meta=league_meta
            )
            simulations_data["by_z_score_selected"] = {
                "m": "z_score",
                "p": sim_periods["selected"],
                "sm": simulation_mode,
                "r": process_simulation_result(sim_z_selected, teams_data)
            }
        except Exception as e:
            print(f"Error in simulation by_z_score_selected ({sim_periods['selected']}): {e}")
            import traceback
            traceback.print_exc()
            simulations_data["by_z_score_selected"] = {
                "m": "z_score",
                "p": sim_periods["selected"],
                "sm": simulation_mode,
                "r": []
            }
        
        # Симуляция по z-score для total (для сравнения)
        try:
            sim_z_total = get_simulation(
                week=current_week,
                mode="z_scores",
                period=sim_periods["total"],
                simulation_mode=simulation_mode,
                top_n_players=top_n_players,
                custom_team_players=custom_team_players_str,
                custom_team_id=main_team_id,
                league_meta=league_meta
            )
            simulations_data["by_z_score_total"] = {
                "m": "z_score",
                "p": sim_periods["total"],
                "sm": simulation_mode,
                "r": process_simulation_result(sim_z_total, teams_data)
            }
        except Exception as e:
            print(f"Error in simulation by_z_score_total: {e}")
            import traceback
            traceback.print_exc()
            simulations_data["by_z_score_total"] = {
                "m": "z_score",
                "p": sim_periods["total"],
                "sm": simulation_mode,
                "r": []
            }
        
        # 9. Рейтинг команд по категориям (для всех команд)
        category_rankings = {}
        
        # Генерируем рейтинги категорий для всех команд
        # Используем первую команду для вызова функции, так как она возвращает данные по всем командам
        try:
            from routers.dashboard import get_category_rankings
            # Используем первую команду из списка, если основная не выбрана
            team_id_for_rankings = main_team_id if main_team_id else teams_data[0]['id'] if teams_data else None
            
            if team_id_for_rankings:
                rankings_data = get_category_rankings(
                    team_id=team_id_for_rankings,
                    period=period,
                    simulation_mode=simulation_mode,
                    top_n_players=top_n_players,
                    custom_team_players=custom_team_players_str,
                    league_meta=league_meta
                )
                
                if 'category_teams' in rankings_data:
                    # Создаем маппинг team_id -> team_name для быстрого доступа
                    team_id_to_name = {team['id']: team['n'] for team in teams_data}
                    
                    # Упрощаем формат рейтингов категорий - ID, название и значение
                    category_rankings_raw = rankings_data['category_teams']
                    for cat, teams_list in category_rankings_raw.items():
                        # Формат: [[rank, team_id, team_name, value], ...] - компактный но с названиями
                        simplified_teams = []
                        for team_data in teams_list:
                            team_id = team_data.get('team_id', 0)
                            team_name = team_id_to_name.get(team_id, 'Unknown')
                            value = team_data.get('value', 0.0)
                            if isinstance(value, float) and not math.isfinite(value):
                                value = 0.0
                            simplified_teams.append([
                                team_data.get('rank', 0),  # rank
                                team_id,  # team_id
                                team_name,  # team_name
                                round(value, 2) if isinstance(value, (int, float)) else value  # value
                            ])
                        category_rankings[cat] = simplified_teams
        except Exception as e:
            pass  # Игнорируем ошибки получения рейтингов
        
        # 10. Метрики лиги (сжатый формат)
        league_metrics = {}
        for cat, metrics in z_data['league_metrics'].items():
            if 'mean' in metrics and 'std' in metrics:
                mean_val = metrics['mean']
                std_val = metrics['std']
                # Очищаем от inf/nan
                if not math.isfinite(mean_val):
                    mean_val = 0.0
                if not math.isfinite(std_val) or std_val <= 0:
                    std_val = 0.01
                
                league_metrics[cat] = [
                    round(mean_val, 2),  # mean
                    round(std_val, 2)  # std
                ]
            elif 'weighted_avg' in metrics:
                weighted_avg_val = metrics['weighted_avg']
                impact_mean_val = metrics.get('impact_mean', 0)
                impact_std_val = metrics.get('impact_std', 0.01)
                
                # Очищаем от inf/nan
                if not math.isfinite(weighted_avg_val):
                    weighted_avg_val = 0.0
                if not math.isfinite(impact_mean_val):
                    impact_mean_val = 0.0
                if not math.isfinite(impact_std_val) or impact_std_val <= 0:
                    impact_std_val = 0.01
                
                league_metrics[cat] = [
                    round(weighted_avg_val, 4),  # weighted_avg
                    round(impact_mean_val, 2),  # impact_mean
                    round(impact_std_val, 2)  # impact_std
                ]
        
        # Формируем итоговый JSON (сжатый формат)
        full_data = {
            "li": league_info,  # league_info
            "t": teams_data,  # teams
            "p": players_data,  # players
            "s": settings_data,  # settings
            "mh": matchup_history,  # main_team_matchup_history
            "um": upcoming_matchups,  # upcoming_matchups
            "fa": fa_data,  # free_agents
            "sim": simulations_data,  # simulations
            "cr": category_rankings,  # category_rankings
            "lm": league_metrics  # league_metrics
        }
        
        # Генерируем системный промпт (с учетом настроек)
        system_prompt = generate_system_prompt(league_info, settings_data)
        
        # Очищаем данные от inf/nan перед сериализацией
        cleaned_data = clean_for_json(full_data)
        
        # Генерируем Markdown формат
        markdown_data = generate_markdown_prompt(cleaned_data)
        final_prompt = f"{system_prompt}\n\n{markdown_data}"
        
        return {
            "prompt": final_prompt,
            "data": cleaned_data
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Error generating prompt: {str(e)}"}

