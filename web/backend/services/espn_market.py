"""ESPN draft-market data used for ADP and draft availability modeling."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict


_CACHE: Dict[tuple[int, int], Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL_SECONDS = 300


def clear_espn_market_cache():
    with _CACHE_LOCK:
        _CACHE.clear()


def _number(value):
    return round(float(value), 2) if isinstance(value, (int, float)) else None


def blended_market_pick(adp, roto_rank):
    """Estimate this lobby's pick market from ESPN's board rank and global ADP.

    Public category draft rooms follow the visible ROTO board very closely in
    the early rounds, while the late player pool becomes noisier and benefits
    from the broader ADP sample. Missing values always fall back safely.
    """
    adp = _number(adp)
    roto = _number(roto_rank)
    if roto is None:
        return adp
    if adp is None:
        return roto
    roto_weight = 0.90 if roto <= 50 else 0.65 if roto <= 100 else 0.60
    return round(roto * roto_weight + adp * (1 - roto_weight), 2)


def _serialize_player(entry: Dict[str, Any]) -> Dict[str, Any] | None:
    player = entry.get("player", {}) or {}
    player_id = player.get("id") or entry.get("id")
    name = player.get("fullName")
    if player_id is None or not name:
        return None

    ownership = player.get("ownership", {}) or {}
    ranks = player.get("draftRanksByRankType", {}) or {}
    standard = ranks.get("STANDARD", {}) or {}
    roto = ranks.get("ROTO", {}) or {}
    espn_adp = _number(ownership.get("averageDraftPosition"))
    espn_roto_rank = roto.get("rank")
    return {
        "player_id": int(player_id),
        "name": name,
        "espn_adp": espn_adp,
        "espn_adp_change": _number(ownership.get("averageDraftPositionPercentChange")),
        "espn_roto_rank": espn_roto_rank,
        "espn_market_pick": blended_market_pick(espn_adp, espn_roto_rank),
        "espn_standard_rank": standard.get("rank"),
        "espn_avg_salary": _number(ownership.get("auctionValueAverage")),
        "espn_percent_owned": _number(ownership.get("percentOwned")),
        "market_updated_at": ownership.get("date"),
    }


def get_espn_market(league_metadata, force: bool = False, limit: int = 500) -> Dict[str, Any]:
    """Return cached ESPN Live Draft Trends keyed by player id and name.

    ESPN exposes the same values used by its Live Draft Trends page inside the
    ``kona_player_info`` response. A stale successful snapshot is retained if a
    later refresh fails so draft assistance does not collapse during a draft.
    """
    key = (int(league_metadata.league_id), int(league_metadata.year))
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and not force and now - cached["cached_at"] < _CACHE_TTL_SECONDS:
            return cached

    filters = {
        "players": {
            "limit": limit,
            "sortAdp": {"sortPriority": 1, "sortAsc": True},
            "sortDraftRanks": {
                "sortPriority": 2,
                "sortAsc": True,
                "value": "ROTO",
            },
        }
    }
    try:
        response = league_metadata.league.espn_request.league_get(
            params={"view": "kona_player_info"},
            headers={"x-fantasy-filter": json.dumps(filters)},
        )
        rows = [
            serialized
            for entry in response.get("players", []) or []
            if (serialized := _serialize_player(entry)) is not None
        ]
        snapshot = {
            "cached_at": now,
            "source": "espn_live_draft_trends",
            "available": bool(rows),
            "players": rows,
            "by_id": {row["player_id"]: row for row in rows},
            "by_name": {row["name"].casefold(): row for row in rows},
        }
        with _CACHE_LOCK:
            _CACHE[key] = snapshot
        return snapshot
    except Exception as error:
        if cached:
            return {**cached, "stale": True, "refresh_error": str(error)}
        return {
            "cached_at": now,
            "source": "espn_live_draft_trends",
            "available": False,
            "players": [],
            "by_id": {},
            "by_name": {},
            "refresh_error": str(error),
        }


def market_for_player(market: Dict[str, Any], player_id=None, name: str | None = None) -> Dict[str, Any]:
    if player_id is not None:
        try:
            match = market.get("by_id", {}).get(int(player_id))
            if match:
                return match
        except (TypeError, ValueError):
            pass
    if name:
        return market.get("by_name", {}).get(name.casefold(), {})
    return {}


def attach_market(record: Dict[str, Any], market: Dict[str, Any], player_id=None, name: str | None = None):
    row = market_for_player(market, player_id=player_id, name=name or record.get("name"))
    for field in (
        "espn_adp",
        "espn_adp_change",
        "espn_roto_rank",
        "espn_market_pick",
        "espn_standard_rank",
        "espn_avg_salary",
        "espn_percent_owned",
        "market_updated_at",
    ):
        record[field] = row.get(field)
    return record
