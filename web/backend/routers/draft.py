"""Live draft API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from dependencies import get_league_meta
from core.config import PERIODS
from services.draft import get_draft_recommendations, get_draft_state


router = APIRouter(prefix="/api/draft", tags=["draft"])


@router.get("/state")
def draft_state(league_meta=Depends(get_league_meta)):
    return get_draft_state(league_meta)


@router.get("/recommendations/{team_id}")
def draft_recommendations(
    team_id: int,
    period: str = PERIODS["projected"],
    punt_categories: str = "",
    mock_player_ids: str = "",
    simulation_slot: int | None = Query(default=None, ge=1, le=30),
    limit: int = Query(default=25, ge=1, le=300),
    league_meta=Depends(get_league_meta),
):
    if league_meta.get_team_by_id(team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    punts = tuple(category.strip() for category in punt_categories.split(",") if category.strip())
    try:
        mock_ids = tuple(int(player_id) for player_id in mock_player_ids.split(",") if player_id.strip())
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid mock player IDs") from error
    return get_draft_recommendations(league_meta, team_id, period, punts, limit, mock_ids, simulation_slot)
