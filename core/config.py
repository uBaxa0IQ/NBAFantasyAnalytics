"""
Конфигурационный файл с данными для подключения к ESPN API.
Содержит только параметры подключения к лиге.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Данные для подключения к ESPN API. Значения по умолчанию сохраняют
# совместимость с текущей лигой; перед новым сезоном задайте их в .env.
LEAGUE_ID = int(os.getenv("LEAGUE_ID", "203950642"))
YEAR = int(os.getenv("SEASON_YEAR", "2026"))
_default_team_id = os.getenv("DEFAULT_TEAM_ID", "").strip()
DEFAULT_TEAM_ID = int(_default_team_id) if _default_team_id else None
ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

PERIODS = {
    "total": f"{YEAR}_total",
    "last_30": f"{YEAR}_last_30",
    "last_15": f"{YEAR}_last_15",
    "last_7": f"{YEAR}_last_7",
    "projected": f"{YEAR}_projected",
    "weighted": f"{YEAR}_weighted",
}
DEFAULT_PERIOD = PERIODS["total"]


def period_key(name: str) -> str:
    """Возвращает ESPN-ключ периода для активного сезона."""
    return PERIODS[name]


def normalize_period(period: str | None) -> str:
    """Мигрирует старые сохраненные ключи периода на активный сезон."""
    if not period:
        return DEFAULT_PERIOD
    if period in PERIODS:
        return PERIODS[period]
    suffix = str(period).split("_", 1)[-1]
    return PERIODS.get(suffix, str(period))

# Fallback для старой 11-category лиги. После подключения к ESPN список
# мутируется на месте, чтобы все модули, импортировавшие CATEGORIES, увидели
# фактические категории подключенной category-лиги.
DEFAULT_CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO']
CATEGORIES = list(DEFAULT_CATEGORIES)
REVERSE_CATEGORIES = {'TO'}

# Коэффициенты для взвешенного периода активного сезона
# Сумма коэффициентов должна быть равна 1.0
WEIGHTED_PERIOD_COEFFS = {
    PERIODS['total']: 0.80,
    PERIODS['last_30']: 0.10,
    PERIODS['last_15']: 0.05,
    PERIODS['last_7']: 0.05
}

# Probabilistic engine defaults. API requests are still clamped by the engine.
MATCHUP_MC_TRIALS = int(os.getenv("MATCHUP_MC_TRIALS", "400"))
SEASON_MC_TRIALS = int(os.getenv("SEASON_MC_TRIALS", "300"))
