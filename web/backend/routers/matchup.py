"""Probabilistic matchup API."""

from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import MATCHUP_MC_TRIALS, PERIODS
from dependencies import get_league_meta
from services.matchup_engine import get_matchup_odds


router = APIRouter(prefix="/api/matchup", tags=["matchup"])


@router.get("/odds")
def matchup_odds(
    team_id: int,
    week: int | None = None,
    period: str = PERIODS["weighted"],
    remaining_only: bool = True,
    trials: int = Query(MATCHUP_MC_TRIALS, ge=100, le=5000),
    league_meta=Depends(get_league_meta),
):
    if league_meta.scoring_type != "H2H_MOST_CATEGORIES":
        raise HTTPException(status_code=422, detail="Вероятностный движок поддерживает H2H Most Categories")
    try:
        return get_matchup_odds(league_meta, team_id, period, week, remaining_only, trials)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
