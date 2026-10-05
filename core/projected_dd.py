"""Projected double-double rates shared by draft and season calculations."""

from datetime import datetime, timezone
import math

from espn_api.basketball.player import Player


_previous_stats_cache = {}
_PREVIOUS_STATS_TTL_SECONDS = 6 * 60 * 60
_PROJECTED_REQUIRED_STATS = ("GP", "PTS", "REB", "AST", "FGM", "FGA", "FTM", "FTA")
_PROJECTED_SPARSE_ZERO_STATS = ("STL", "BLK", "3PM", "3PA", "TO")
_DD_FEATURES = ("PTS", "REB", "AST", "STL", "BLK")
_DD_SCALES = (6.0, 2.5, 2.5, 1.0, 1.0)


def raw_average(player, period):
    data = (getattr(player, "stats", {}) or {}).get(period, {})
    stats = data.get("avg") if isinstance(data, dict) else None
    if not isinstance(stats, dict) or not stats:
        return None
    return {
        key: float(value) if value is not None else 0.0
        for key, value in stats.items()
        if isinstance(value, (int, float)) or value is None
    }


def normalize_projected_stats(stats):
    """Validate projections and restore ESPN fields omitted when equal to zero."""
    if not isinstance(stats, dict):
        return None
    normalized = {}
    for key, value in stats.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if not math.isfinite(number) or number < 0:
                return None
            normalized[key] = number
    if any(key not in normalized for key in _PROJECTED_REQUIRED_STATS):
        return None
    if normalized["GP"] <= 0:
        return None
    for key in _PROJECTED_SPARSE_ZERO_STATS:
        normalized.setdefault(key, 0.0)
    for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "3PA")):
        if normalized[made] > normalized[attempted] + 1e-9:
            return None
    normalized["FG%"] = normalized["FGM"] / normalized["FGA"] if normalized["FGA"] else 0.0
    normalized["FT%"] = normalized["FTM"] / normalized["FTA"] if normalized["FTA"] else 0.0
    normalized["3PT%"] = normalized["3PM"] / normalized["3PA"] if normalized["3PA"] else 0.0
    normalized["A/TO"] = normalized["AST"] / normalized["TO"] if normalized["TO"] else normalized["AST"]
    return normalized


def _fallback_double_double_rate(stats):
    """Approximate P(at least two categories reach 10) from per-game means."""
    probabilities = []
    for key, scale in (("PTS", 3.0), ("REB", 1.8), ("AST", 1.8), ("STL", .8), ("BLK", .8)):
        mean = float(stats.get(key, 0.0) or 0.0)
        probabilities.append(1.0 / (1.0 + math.exp(max(-30.0, min(30.0, (10.0 - mean) / scale)))))
    zero = math.prod(1.0 - probability for probability in probabilities)
    exactly_one = sum(probabilities[index] * math.prod(
        1.0 - other for other_index, other in enumerate(probabilities) if other_index != index
    ) for index in range(len(probabilities)))
    return max(0.0, min(1.0, 1.0 - zero - exactly_one))


def estimate_projected_double_doubles(projected, historical):
    """Fill missing projected DD rates using prior results and peer calibration."""
    training = []
    for player_id, stats in historical.items():
        if not isinstance(stats, dict) or "DD" not in stats or float(stats.get("GP", 0) or 0) < 5:
            continue
        features = tuple(float(stats.get(key, 0.0) or 0.0) for key in _DD_FEATURES)
        training.append((int(player_id), features, max(0.0, min(1.0, float(stats["DD"])))))

    def peer_rate(stats):
        if not training:
            return _fallback_double_double_rate(stats)
        target = tuple(float(stats.get(key, 0.0) or 0.0) for key in _DD_FEATURES)
        nearest = []
        for _, features, rate in training:
            distance = math.sqrt(sum(((left - right) / scale) ** 2
                                     for left, right, scale in zip(target, features, _DD_SCALES)))
            nearest.append((distance, rate))
        nearest.sort(key=lambda row: row[0])
        nearest = nearest[:12]
        weights = [math.exp(-distance) for distance, _ in nearest]
        if sum(weights) <= 1e-12:
            return _fallback_double_double_rate(stats)
        return sum(weight * row[1] for weight, row in zip(weights, nearest)) / sum(weights)

    result = {}
    sources = {}
    for player_id, stats in projected.items():
        row = dict(stats)
        if "DD" in row:
            sources[player_id] = "espn_projected"
            result[player_id] = row
            continue
        current_peer = peer_rate(row)
        prior = historical.get(player_id) or {}
        if "DD" in prior and float(prior.get("GP", 0) or 0) >= 5:
            prior_rate = max(0.0, min(1.0, float(prior["DD"])))
            prior_peer = max(.01, peer_rate(prior))
            role_factor = max(.4, min(2.5, current_peer / prior_peer))
            adjusted_prior = max(0.0, min(1.0, prior_rate * role_factor))
            reliability = min(.8, float(prior.get("GP", 0) or 0) / 82.0)
            row["DD"] = reliability * adjusted_prior + (1.0 - reliability) * current_peer
            sources[player_id] = "derived_prior_and_peers"
        else:
            row["DD"] = current_peer
            sources[player_id] = "derived_peers"
        result[player_id] = row
    return result, sources


def previous_season_stats(league_metadata, player_ids):
    """Load historical NBA stats through the current league player-card API."""
    if not player_ids or league_metadata.year <= 1:
        return {}
    try:
        previous_year = league_metadata.year - 1
        league = league_metadata.league
        unique_ids = [int(player_id) for player_id in dict.fromkeys(player_ids) if player_id]
        cache_key = (league_metadata.league_id, previous_year)
        now = datetime.now(timezone.utc)
        cached = _previous_stats_cache.get(cache_key)
        if not cached or (now - cached["saved_at"]).total_seconds() > _PREVIOUS_STATS_TTL_SECONDS:
            cached = {"saved_at": now, "requested": set(), "data": {}}
            _previous_stats_cache[cache_key] = cached

        missing_ids = [player_id for player_id in unique_ids if player_id not in cached["requested"]]
        for start in range(0, len(missing_ids), 50):
            batch = missing_ids[start:start + 50]
            raw = league.espn_request.get_player_card(
                batch,
                league.finalScoringPeriod,
                [f"00{previous_year}", f"10{previous_year}"],
            )
            cached["requested"].update(batch)
            for row in raw.get("players", []) or []:
                player = Player(row, previous_year)
                stats = raw_average(player, f"{previous_year}_total")
                if stats and getattr(player, "playerId", None) is not None:
                    cached["data"][int(player.playerId)] = stats
        cached["saved_at"] = now
        return {
            player_id: cached["data"][player_id]
            for player_id in unique_ids
            if player_id in cached["data"]
        }
    except Exception as error:
        print(f"Не удалось загрузить статистику прошлого сезона: {error}")
        return {}
