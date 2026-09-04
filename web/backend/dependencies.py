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
from fastapi import HTTPException
from threading import Lock
from datetime import datetime, timezone

_refresh_lock = Lock()


@lru_cache()
def get_league_meta():
    """
    Получает экземпляр LeagueMetadata.
    Использует lru_cache для создания singleton.
    
    Returns:
        LeagueMetadata: Экземпляр LeagueMetadata
    """
    league_meta = LeagueMetadata()
    if not league_meta.connect_to_league():
        raise HTTPException(status_code=503, detail="ESPN недоступен. Повторите попытку позже.")
    league_meta.last_refresh_time = datetime.now(timezone.utc)
    return league_meta


def refresh_cached_league():
    """Retain the last successful object on failure; serialize refreshes."""
    with _refresh_lock:
        return get_league_meta().refresh_league()

