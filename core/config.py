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

