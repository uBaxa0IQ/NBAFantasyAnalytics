"""API календарных проекций составов."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_league_meta
from core.config import PERIODS
from services.projections import project_league_matchup, project_scheduled_matchups, project_team_matchup


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


@router.get("/season")
def get_season_projection(
    period: str = PERIODS["weighted"],
    calculation_engine: str = "calendar",
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_id: Optional[int] = None,
    custom_team_players: Optional[str] = None,
    league_meta=Depends(get_league_meta),
):
    from services.season import project_regular_season

    return project_regular_season(
        league_meta, period, calculation_engine,
        simulation_mode=simulation_mode, top_n_players=top_n_players,
        custom_team_id=custom_team_id,
        custom_team_players=tuple(custom_team_players.split(',')) if custom_team_players else (),
    )


@router.get("/matchups")
def get_scheduled_matchups(
    matchup_period: int,
    period: str = PERIODS["weighted"],
    simulation_mode: str = "all",
    top_n_players: int = 13,
    custom_team_id: Optional[int] = None,
    custom_team_players: Optional[str] = None,
    league_meta=Depends(get_league_meta),
):
    last_week = max((int(week) for week in league_meta.league.settings.matchup_periods), default=0)
    current_week = int(league_meta.league.currentMatchupPeriod)
    if matchup_period < current_week or matchup_period > last_week:
        raise HTTPException(status_code=422, detail="Выберите текущую или будущую неделю лиги")
    return project_scheduled_matchups(
        league_meta, period, matchup_period,
        simulation_mode=simulation_mode, top_n_players=top_n_players,
        custom_team_id=custom_team_id,
        custom_team_players=tuple(custom_team_players.split(',')) if custom_team_players else (),
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
