"""
Тестовый скрипт для проверки возможностей ESPN API в период плей-офф.

Запуск из корня проекта:
  python scripts/test_playoff_api.py

Требуется .env с ESPN_S2 и SWID (см. .env.example).
"""

import os
import sys
from pathlib import Path

# Корень проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "core"))

# Загрузка .env из корня
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from core.league_metadata import LeagueMetadata


def main():
    print("=== Проверка ESPN API для плей-офф (неделя 17+) ===\n")

    league_meta = LeagueMetadata()
    if not league_meta.connect_to_league():
        print("Ошибка: не удалось подключиться к лиге. Проверьте .env (ESPN_S2, SWID).")
        return 1

    league = league_meta.league
    current_week = league.currentMatchupPeriod
    teams = league_meta.get_teams()

    print(f"Текущая неделя (currentMatchupPeriod): {current_week}")
    print(f"Количество команд: {len(teams)}")
    print()

    # Атрибуты объекта league (поиск playoff-специфичных полей)
    print("--- Атрибуты объекта league ---")
    for attr in sorted(dir(league)):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(league, attr)
            if callable(val):
                continue
            # Не печатаем огромные объекты
            s = repr(val)
            if len(s) > 120:
                s = s[:117] + "..."
            print(f"  {attr}: {s}")
        except Exception as e:
            print(f"  {attr}: <error: {e}>")
    print()

    # Посевы: порядок команд в standings / по wins
    print("--- Посевы (по wins, как в лиге) ---")
    teams_sorted = sorted(
        teams,
        key=lambda t: (getattr(t, "wins", 0), -getattr(t, "losses", 999)),
        reverse=True,
    )
    for i, t in enumerate(teams_sorted, 1):
        w = getattr(t, "wins", "?")
        l = getattr(t, "losses", "?")
        print(f"  {i}. {t.team_name} (id={t.team_id})  W-L: {w}-{l}")
    print()

    # Матчапы за текущую неделю (для плей-офф — пары 1-8, 2-7, 3-6, 4-5 и т.д.)
    print(f"--- Матчапы за неделю {current_week} (box_scores) ---")
    try:
        box_scores = league.box_scores(matchup_period=current_week)
    except Exception as e:
        print(f"  Ошибка: {e}")
        box_scores = []

    if not box_scores:
        print("  Нет данных (пустой список или API не вернул матчапы).")
    else:
        for box in box_scores:
            home = box.home_team
            away = box.away_team
            print(f"  {home.team_name} (id={home.team_id}) vs {away.team_name} (id={away.team_id})")
    print()

    # Проверка недели 17 и 18 явно (если текущая неделя уже 17+)
    for week in [17, 18]:
        if week == current_week:
            continue
        print(f"--- Матчапы за неделю {week} (проверка наличия) ---")
        try:
            bs = league.box_scores(matchup_period=week)
            if bs:
                for box in bs:
                    print(f"  {box.home_team.team_name} vs {box.away_team.team_name}")
            else:
                print("  Пусто.")
        except Exception as e:
            print(f"  Ошибка: {e}")
        print()

    # get_matchups_for_week через league_meta
    print(f"--- get_matchups_for_week({current_week}) ---")
    matchups = league_meta.get_matchups_for_week(current_week)
    for m in matchups:
        print(f"  {m['team1']} vs {m['team2']} (id: {m['team1_id']}, {m['team2_id']})")
    if not matchups:
        print("  Пусто.")
    print()

    # get_matchup_box_score для первой команды (пример)
    if teams:
        tid = teams[0].team_id
        print(f"--- get_matchup_box_score(week={current_week}, team_id={tid}) ---")
        box = league_meta.get_matchup_box_score(current_week, tid)
        if box:
            print(f"  Команда: {box.get('team_name')}, соперник: {box.get('opponent_name')}")
            print(f"  Ключи в box: {list(box.keys())}")
        else:
            print("  None")
    print()

    print("=== Конец проверки ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
