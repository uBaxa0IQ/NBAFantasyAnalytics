"""Безопасная проверка готовности лиги к запуску."""

import os
import sys

from .config import DEFAULT_TEAM_ID, ESPN_S2, LEAGUE_ID, SWID, YEAR
from .league_metadata import LeagueMetadata


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    errors = []
    if not os.getenv("LEAGUE_ID"):
        errors.append("LEAGUE_ID не задан в .env")
    if not os.getenv("SEASON_YEAR"):
        errors.append("SEASON_YEAR не задан в .env")
    if not ESPN_S2 or not SWID:
        errors.append("ESPN_S2/SWID не заданы")

    league = LeagueMetadata()
    connected = league.connect_to_league() if ESPN_S2 and SWID else False
    teams = league.get_teams() if connected else []
    if not connected:
        errors.append("не удалось подключиться к ESPN")
    elif not teams:
        errors.append("ESPN не вернул команды")
    elif DEFAULT_TEAM_ID is not None and not any(
        int(team.team_id) == int(DEFAULT_TEAM_ID) for team in teams
    ):
        errors.append("DEFAULT_TEAM_ID отсутствует в этой лиге")

    print(f"Сезон: {YEAR}; лига: {LEAGUE_ID}; команд: {len(teams)}")
    if errors:
        print("Не готово:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Готово: ESPN доступен, лига и команда определены корректно.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
