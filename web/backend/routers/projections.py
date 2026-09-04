"""API календарных проекций составов."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_league_meta
from core.config import PERIODS
from services.projections import project_league_matchup, project_team_matchup


router = APIRouter(prefix="/api/projections", tags=["projections"])


@router.get('/validation')
def forecast_validation(league_meta=Depends(get_league_meta)):
    from services.forecast_history import validate
    return validate(league_meta)


@router.get("/league")
def get_league_projection(
    period: str = PERIODS["weighted"],
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: str = "",
    league_meta=Depends(get_league_meta),
):
    return project_league_matchup(
        league_meta,
        period,
        matchup_period,
        remaining_only,
        [category.strip() for category in punt_categories.split(",") if category.strip()],
    )


@router.get("/team/{team_id}")
def get_team_projection(
    team_id: int,
    period: str = PERIODS["weighted"],
    matchup_period: Optional[int] = None,
    remaining_only: bool = False,
    punt_categories: str = "",
    league_meta=Depends(get_league_meta),
):
    try:
        return project_team_matchup(
            league_meta,
            team_id,
            period,
            matchup_period,
            remaining_only,
            [category.strip() for category in punt_categories.split(",") if category.strip()],
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
