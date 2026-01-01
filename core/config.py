"""
Конфигурационный файл с данными для подключения к ESPN API.
Содержит только параметры подключения к лиге.
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Данные для подключения к ESPN API
LEAGUE_ID = 203950642
YEAR = 2026
ESPN_S2 = os.getenv("ESPN_S2")
SWID = os.getenv("SWID")

# Категории статистики для фэнтези лиги (11 категорий)
# Используются ключи напрямую из ESPN API
CATEGORIES = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'DD', 'FG%', 'FT%', '3PT%', 'A/TO']

# Коэффициенты для взвешенного периода (2026_weighted)
# Сумма коэффициентов должна быть равна 1.0
WEIGHTED_PERIOD_COEFFS = {
    '2026_total': 0.40,
    '2026_last_30': 0.30,
    '2026_last_15': 0.20,
    '2026_last_7': 0.10
}

WEIGHTED_PERIOD_COEFFS = {
    '2026_total': 0.80,
    '2026_last_30': 0.10,
    '2026_last_15': 0.05,
    '2026_last_7': 0.05
}
