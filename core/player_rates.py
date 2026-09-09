"""Player-level inputs for the probabilistic matchup engine.

The module contains no ESPN I/O.  It turns already fetched per-game period rows
into a stable mean, a conservative per-game spread and an availability prior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import sqrt
from typing import Any, Mapping


RATE_MODEL_VERSION = "player-rates-v1"

COUNT_CV = {
    "PTS": 0.42, "REB": 0.55, "AST": 0.58, "STL": 0.92,
    "BLK": 1.05, "3PM": 0.72, "DD": 1.15, "TO": 0.62,
    "FGM": 0.48, "FGA": 0.34, "FTM": 0.70, "FTA": 0.60,
    "3PA": 0.48,
}

STATUS_PRIORS = {
    "ACTIVE": 1.0,
    "HEALTHY": 1.0,
    "DAY_TO_DAY": 0.55,
    "DTD": 0.55,
    "QUESTIONABLE": 0.40,
    "DOUBTFUL": 0.25,
    "OUT": 0.0,
    "INJURY_RESERVE": 0.0,
    "IR": 0.0,
}


@dataclass(frozen=True)
class PlayerRate:
    player_id: int | None
    name: str
    mean: dict[str, float]
    std: dict[str, float]
    p_play: float
    injury_status: str
    games_sample: int
    model_version: str = RATE_MODEL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(row: Mapping[str, Any] | None, key: str) -> float | None:
    value = (row or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def availability_probability(player: Mapping[str, Any]) -> float:
    """Return a documented prior; confirmed IR/OUT stays unavailable."""
    if str(player.get("lineup_slot") or "").upper() == "IR":
        return 0.0
    status = str(player.get("injury_status") or "ACTIVE").upper().replace(" ", "_")
    if not player.get("injured") and status not in STATUS_PRIORS:
        return 1.0
    return STATUS_PRIORS.get(status, 0.70 if player.get("injured") else 1.0)


def build_player_rate(
    player: Mapping[str, Any],
    season: Mapping[str, Any] | None = None,
    recent: Mapping[str, Any] | None = None,
    projected: Mapping[str, Any] | None = None,
    empirical_std: Mapping[str, Any] | None = None,
) -> PlayerRate:
    """Reliability-shrunk form adjustment around the season baseline.

    ESPN's rolling windows overlap the season row.  Treating recent form as an
    adjustment avoids counting the same games as independent observations.
    """
    fallback = player.get("stats") or {}
    season = season or fallback
    recent = recent or {}
    projected = projected or {}
    games = int(_number(season, "GP") or _number(fallback, "GP") or 0)
    recent_games = int(_number(recent, "GP") or 0)
    recent_reliability = min(0.45, recent_games / (recent_games + 18.0)) if recent_games else 0.0
    projection_reliability = 0.12 if projected else 0.0

    keys = set(COUNT_CV) | set(season) | set(recent) | set(projected)
    mean: dict[str, float] = {}
    std: dict[str, float] = {}
    for key in keys:
        base = _number(season, key)
        if base is None:
            base = _number(fallback, key)
        if base is None:
            continue
        value = base
        form = _number(recent, key)
        if form is not None:
            value += recent_reliability * (form - base)
        role = _number(projected, key)
        if role is not None:
            value += projection_reliability * (role - base)
        value = max(0.0, value)
        mean[key] = value
        if key in COUNT_CV:
            # Small floor protects low-frequency categories from zero variance.
            empirical = _number(empirical_std, key)
            fallback_std = max(0.12, value * COUNT_CV[key]) * sqrt(1.0 + 6.0 / max(games, 1))
            # Shrink noisy short histories toward the category fallback.
            if empirical is not None and empirical >= 0:
                std[key] = 0.60 * empirical + 0.40 * fallback_std
            else:
                std[key] = fallback_std

    # Ratios are always derived from their components in aggregation/simulation.
    for ratio in ("FG%", "FT%", "3PT%", "A/TO"):
        mean.pop(ratio, None)
        std.pop(ratio, None)

    return PlayerRate(
        player_id=player.get("player_id"),
        name=str(player.get("name") or ""),
        mean=mean,
        std=std,
        p_play=availability_probability(player),
        injury_status=str(player.get("injury_status") or "ACTIVE"),
        games_sample=games,
    )


def attach_player_rates(
    players: list[dict[str, Any]],
    period_rows: Mapping[str, Mapping[Any, Mapping[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Attach rates to projection players, keyed by player id (name fallback)."""
    period_rows = period_rows or {}
    output = []
    for player in players:
        identity = player.get("player_id") or player.get("name")
        rate = build_player_rate(
            player,
            period_rows.get("season", {}).get(identity),
            period_rows.get("recent", {}).get(identity),
            period_rows.get("projected", {}).get(identity),
            period_rows.get("std", {}).get(identity),
        )
        output.append({**player, "rate": rate.as_dict(), "stats": rate.mean, "p_play": rate.p_play})
    return output
