"""Публичные пользовательские настройки аналитики."""

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.config import DEFAULT_PERIOD, DEFAULT_TEAM_ID, LEAGUE_ID, PERIODS, YEAR
from core.league_metadata import LeagueMetadata
from core.runtime_settings import (
    get_draft_connection_mode,
    load_runtime_settings,
    save_draft_connection_mode,
    save_runtime_league_id,
)
from core.weighted_coefficients import (
    load_weighted_coefficients,
    save_weighted_coefficients,
)
from dependencies import get_league_meta


router = APIRouter(prefix="/api/settings", tags=["settings"])


class WeightedCoefficientsRequest(BaseModel):
    total: float = Field(ge=0, le=1, allow_inf_nan=False)
    last_30: float = Field(ge=0, le=1, allow_inf_nan=False)
    last_15: float = Field(ge=0, le=1, allow_inf_nan=False)
    last_7: float = Field(ge=0, le=1, allow_inf_nan=False)


class LeagueConnectionRequest(BaseModel):
    league_id: int = Field(gt=0)


class DraftConnectionModeRequest(BaseModel):
    mode: str


def effective_default_team_id(league_meta):
    teams = list(league_meta.get_teams() or [])
    if not teams:
        return None
    # DEFAULT_TEAM_ID belongs to the originally configured league.  When the
    # user switches leagues, prefer the team owned by the authenticated ESPN
    # member; merely finding the old numeric id in the new league is not enough.
    try:
        swid = str(league_meta.swid or "").upper()
        raw_teams = league_meta.league.espn_request.get_league().get("teams", []) or []
        owned = next((
            int(team["id"])
            for team in raw_teams
            if swid and swid in [str(owner).upper() for owner in team.get("owners", []) or []]
        ), None)
        if owned is not None:
            return owned
    except Exception:
        pass
    if DEFAULT_TEAM_ID is not None and any(int(team.team_id) == int(DEFAULT_TEAM_ID) for team in teams):
        return int(DEFAULT_TEAM_ID)
    return int(teams[0].team_id)


def serialize_coefficients():
    coefficients = load_weighted_coefficients()
    return {
        "total": coefficients[PERIODS["total"]],
        "last_30": coefficients[PERIODS["last_30"]],
        "last_15": coefficients[PERIODS["last_15"]],
        "last_7": coefficients[PERIODS["last_7"]],
    }


def serialize_season(league_meta=None):
    runtime_settings = load_runtime_settings()
    season = {
        "league_id": league_meta.league_id if league_meta is not None else runtime_settings.get("league_id", LEAGUE_ID),
        "year": YEAR,
        "default_team_id": effective_default_team_id(league_meta) if league_meta is not None else DEFAULT_TEAM_ID,
        "default_period": DEFAULT_PERIOD,
        "periods": PERIODS,
        "configured_from_env": {
            "league_id": bool(os.getenv("LEAGUE_ID")),
            "year": bool(os.getenv("SEASON_YEAR")),
            "default_team_id": bool(os.getenv("DEFAULT_TEAM_ID")),
        },
        "runtime_override": {"league_id": "league_id" in runtime_settings},
        "draft_connection_mode": get_draft_connection_mode(),
    }


    if league_meta is not None:
        season.update({
            "categories": league_meta.get_categories(),
            "reverse_categories": sorted(league_meta.reverse_categories),
            "scoring_type": league_meta.scoring_type,
            "category_mode_supported": league_meta.category_mode_supported,
        })
    return season


@router.put("/draft-connection-mode")
def update_draft_connection_mode(
    request: DraftConnectionModeRequest,
    league_meta=Depends(get_league_meta),
):
    mode = request.mode.lower()
    if mode not in {"espn", "analytics"}:
        raise HTTPException(status_code=400, detail="Неизвестный режим подключения к драфту")
    try:
        save_draft_connection_mode(mode)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Не удалось сохранить режим драфта") from error

    from services.draft_live import live_draft_client
    if mode == "espn":
        live_draft_client.stop()
    else:
        # Start the connection immediately; the frontend doesn't need a reload
        # or to wait for its next polling interval.
        from services.draft import get_draft_state
        get_draft_state(league_meta)
    return {"mode": mode, "connected_by_analytics": mode == "analytics"}


@router.get("")
def get_settings(league_meta=Depends(get_league_meta)):
    return {
        "weighted_coefficients": serialize_coefficients(),
        "season": serialize_season(league_meta),
    }


@router.put("/league")
def update_league_connection(request: LeagueConnectionRequest):
    """Validate and persist a league switch without exposing ESPN credentials."""
    candidate = LeagueMetadata(league_id=request.league_id)
    if not candidate.connect_to_league() or not candidate.get_teams():
        raise HTTPException(
            status_code=400,
            detail="Не удалось подключиться к этой лиге. Проверьте League ID и доступ текущего ESPN-аккаунта.",
        )
    try:
        save_runtime_league_id(request.league_id)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="Не удалось сохранить League ID") from error

    # Every one of these caches is scoped to the old league connection.
    from services.draft import _previous_stats_cache
    from services.draft_live import live_draft_client
    from services.espn_market import clear_espn_market_cache

    live_draft_client.stop()
    clear_espn_market_cache()
    _previous_stats_cache.clear()
    get_league_meta.cache_clear()
    return {
        "success": True,
        "season": serialize_season(candidate),
        "teams": [
            {"team_id": team.team_id, "team_name": team.team_name}
            for team in candidate.get_teams()
        ],
    }


@router.get("/readiness")
def get_readiness(league_meta=Depends(get_league_meta)):
    warnings = []
    if not os.getenv("LEAGUE_ID"):
        warnings.append("LEAGUE_ID не задан в .env; используется совместимое значение по умолчанию")
    if not os.getenv("SEASON_YEAR"):
        warnings.append("SEASON_YEAR не задан в .env; используется совместимое значение по умолчанию")
    if not os.getenv("ESPN_S2") or not os.getenv("SWID"):
        warnings.append("Не заданы действующие ESPN_S2/SWID")
    connected = bool(getattr(league_meta, "league", None))
    teams = getattr(league_meta, "teams", []) or []
    if not connected:
        warnings.append("Нет подключения к ESPN")
    elif not teams:
        warnings.append("ESPN не вернул команды новой лиги")
    effective_team_id = effective_default_team_id(league_meta) if teams else None
    default_team_exists = effective_team_id is not None
    if not default_team_exists:
        warnings.append("DEFAULT_TEAM_ID отсутствует в подключенной лиге")
    return {
        "ready": not warnings,
        "season": serialize_season(league_meta),
        "espn_connected": connected,
        "team_count": len(teams),
        "default_team_exists": default_team_exists,
        "warnings": warnings,
    }


@router.get("/weighted-coefficients")
def get_weighted_coefficients():
    return serialize_coefficients()


@router.put("/weighted-coefficients")
def update_weighted_coefficients(request: WeightedCoefficientsRequest):
    values = [request.total, request.last_30, request.last_15, request.last_7]
    if any(value < 0 or value > 1 for value in values):
        raise HTTPException(
            status_code=400,
            detail="Каждый коэффициент должен быть в диапазоне от 0 до 1",
        )

    total = sum(values)
    if abs(total - 1.0) > 0.001:
        raise HTTPException(
            status_code=400,
            detail=f"Сумма коэффициентов должна быть равна 1. Текущая сумма: {total:.3f}",
        )

    coefficients = {
        PERIODS["total"]: request.total,
        PERIODS["last_30"]: request.last_30,
        PERIODS["last_15"]: request.last_15,
        PERIODS["last_7"]: request.last_7,
    }
    try:
        save_weighted_coefficients(coefficients)
    except OSError as error:
        raise HTTPException(status_code=500, detail="Не удалось сохранить коэффициенты") from error

    return {"success": True, "coefficients": serialize_coefficients()}
