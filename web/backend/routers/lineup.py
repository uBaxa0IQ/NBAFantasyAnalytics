"""Calendar-aware daily lineup optimization."""

from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD
from services.projections import project_team_matchup
from services.legacy import rank_lineup_legacy


router = APIRouter(prefix="/api/lineup", tags=["lineup"])


@router.get("/{team_id}/optimize")
def optimize_team_lineup(
    team_id: int,
    period: str = DEFAULT_PERIOD,
    matchup_period: int | None = None,
    remaining_only: bool = True,
    punt_categories: str = "",
    calculation_engine: str = "calendar",
    league_meta=Depends(get_league_meta),
):
    """Return the best valid lineup for every remaining scoring day."""
    punts = tuple(
        category.strip()
        for category in punt_categories.split(",")
        if category.strip()
    )
    if calculation_engine == "legacy":
        try:
            return rank_lineup_legacy(league_meta, team_id, period, punts)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = project_team_matchup(
            league_meta,
            team_id=team_id,
            period=period,
            matchup_period=matchup_period,
            remaining_only=remaining_only,
            punt_categories=punts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    matchup = league_meta.get_matchup_box_score(result["matchup_period"], team_id)
    result["matchup_info"] = (
        {
            "opponent_name": matchup["opponent_name"],
            "opponent_id": matchup["opponent_id"],
            "week": result["matchup_period"],
        }
        if matchup
        else None
    )
    result["punt_categories"] = list(punts)
    result["method"] = "daily_slot_and_schedule_optimization"
    return result
