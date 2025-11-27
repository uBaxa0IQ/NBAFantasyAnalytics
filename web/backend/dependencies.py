"""
Зависимости для dependency injection.
"""
import sys
import os

# Добавляем путь к проекту и core
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'core'))

from core.league_metadata import LeagueMetadata
from functools import lru_cache


@lru_cache()
def get_league_meta():
    """
    Получает экземпляр LeagueMetadata.
    Использует lru_cache для создания singleton.
    
    Returns:
        LeagueMetadata: Экземпляр LeagueMetadata
    """
    league_meta = LeagueMetadata()
    league_meta.connect_to_league()
    return league_meta

