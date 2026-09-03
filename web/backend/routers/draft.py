"""Live draft API."""

from fastapi import APIRouter, Depends, HTTPException, Query
from dependencies import get_league_meta
from core.config import CATEGORIES, PERIODS
from services.draft import get_draft_recommendations, get_draft_state
from services.draft_benchmark import benchmark_adaptive_vs_legacy, benchmark_draft_strategies, benchmark_punt_strategies
from services.draft_learning import learning_dataset_stats


STANDARD_8_CATEGORIES = ("FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "PTS")
CUSTOM_11_CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")


router = APIRouter(prefix="/api/draft", tags=["draft"])


@router.get("/learning-stats")
def draft_learning_stats():
    return learning_dataset_stats()


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


@router.get("/benchmark/{team_id}")
def draft_benchmark(
    team_id: int,
    period: str = PERIODS["projected"],
    punt_category: str = "FG%",
    runs_per_slot: int = Query(default=60, ge=5, le=500),
    slot: int | None = Query(default=None, ge=1, le=30),
    league_meta=Depends(get_league_meta),
):
    if league_meta.get_team_by_id(team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if punt_category not in CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Unknown punt category: {punt_category}")
    recommendations = get_draft_recommendations(
        league_meta,
        team_id,
        period,
        (),
        300,
        (),
        None,
        False,
        True,
    )
    team_count = max(1, len(league_meta.get_teams()))
    if slot is not None and slot > team_count:
        raise HTTPException(status_code=400, detail=f"Draft slot must be between 1 and {team_count}")
    selected_slots = [slot] if slot is not None else None
    return benchmark_draft_strategies(
        recommendations["players"],
        team_count,
        recommendations["draft_rounds"],
        punt_category=punt_category,
        runs_per_slot=runs_per_slot,
        slots=selected_slots,
        roster_slots=recommendations.get("roster_slots"),
    )


@router.get("/punt-benchmark/{team_id}")
def draft_punt_benchmark(
    team_id: int,
    period: str = PERIODS["projected"],
    format: str = Query(default="standard8", pattern="^(standard8|custom11)$"),
    max_punts: int = Query(default=2, ge=0, le=3),
    screening_runs: int = Query(default=1, ge=1, le=10),
    deep_runs: int = Query(default=10, ge=2, le=100),
    league_meta=Depends(get_league_meta),
):
    if league_meta.get_team_by_id(team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    recommendations = get_draft_recommendations(
        league_meta, team_id, period, (), 300, (), None, False, True,
    )
    categories = STANDARD_8_CATEGORIES if format == "standard8" else CUSTOM_11_CATEGORIES
    return benchmark_punt_strategies(
        recommendations["players"],
        max(1, len(league_meta.get_teams())),
        recommendations["draft_rounds"],
        categories,
        max_punts=max_punts,
        roster_slots=recommendations.get("roster_slots"),
        screening_runs=screening_runs,
        deep_runs=deep_runs,
        finalist_count=10 if format == "standard8" else 12,
    )


@router.get("/adaptive-benchmark/{team_id}")
def draft_adaptive_benchmark(
    team_id: int,
    period: str = PERIODS["projected"],
    format: str = Query(default="standard8", pattern="^(standard8|custom11)$"),
    runs_per_slot: int = Query(default=5, ge=1, le=30),
    league_meta=Depends(get_league_meta),
):
    if league_meta.get_team_by_id(team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    recommendations = get_draft_recommendations(
        league_meta, team_id, period, (), 300, (), None, False, True,
    )
    categories = STANDARD_8_CATEGORIES if format == "standard8" else CUSTOM_11_CATEGORIES
    return benchmark_adaptive_vs_legacy(
        recommendations["players"],
        max(1, len(league_meta.get_teams())),
        recommendations["draft_rounds"],
        categories,
        roster_slots=recommendations.get("roster_slots"),
        runs_per_slot=runs_per_slot,
    )
