"""
Роутер для публичных настроек лиги.
"""
from fastapi import APIRouter
from utils.settings import load_league_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

@router.get("")
def get_league_settings():
    """
    Получает публичные настройки лиги.
    """
    return load_league_settings()







