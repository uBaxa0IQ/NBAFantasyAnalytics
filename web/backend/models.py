"""
Pydantic модели для API запросов.
"""
from pydantic import BaseModel
from typing import List


class TradeAnalysisRequest(BaseModel):
    """Модель для анализа трейда."""
    my_team_id: int
    their_team_id: int
    i_give: List[str]  # Имена игроков
    i_receive: List[str]
    period: str = "2026_total"
    punt_categories: List[str] = []
    scope_mode: str = "team"  # "team" или "trade"
    exclude_ir: bool = False


class TeamTrade(BaseModel):
    """Модель для трейда одной команды в мультикомандном трейде."""
    team_id: int
    give: List[str]  # Имена игроков, которых отдает команда
    receive: List[str]  # Имена игроков, которых получает команда


class MultiTeamTradeRequest(BaseModel):
    """Модель для анализа мультикомандного трейда."""
    trades: List[TeamTrade]  # Список команд и их трейдов
    period: str = "2026_total"
    punt_categories: List[str] = []
    exclude_ir: bool = False




