"""Неизменяемый снимок данных лиги для расчётов одного запроса."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Tuple
from time import monotonic

from .z_score import calculate_z_scores_from_players
from .roster_rules import league_slots
from .projection import DEFAULT_LINEUP_SLOTS


@dataclass(frozen=True)
class PlayerSnapshot:
    player_id: int | None
    name: str
    fantasy_team_id: int
    fantasy_team_name: str
    position: str
    eligible_slots: Tuple[str, ...]
    lineup_slot: str
    injured: bool
    injury_status: str
    pro_team: str | None
    schedule: Dict[str, Any]
    stats: Dict[str, float]
    z_scores: Dict[str, float]
    expected_return_date: Any = None

    @property
    def available(self) -> bool:
        return self.lineup_slot != "IR" and not (
            self.injured and self.injury_status == "OUT"
        )

    def as_projection_player(self) -> Dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "eligible_slots": list(self.eligible_slots),
            "schedule": self.schedule,
            "stats": self.stats,
            "z_scores": self.z_scores,
            "available": self.available,
            "injured": self.injured,
            "injury_status": self.injury_status,
            "expected_return_date": self.expected_return_date,
            "lineup_slot": self.lineup_slot,
        }


@dataclass(frozen=True)
class LeagueSnapshot:
    period: str
    created_at: datetime
    current_matchup_period: int
    current_scoring_period: int
    players: Tuple[PlayerSnapshot, ...]
    league_metrics: Dict[str, Any]
    active_slots: Tuple[str, ...] = DEFAULT_LINEUP_SLOTS

    def team_players(self, team_id: int) -> Tuple[PlayerSnapshot, ...]:
        return tuple(player for player in self.players if player.fantasy_team_id == team_id)


def build_league_snapshot(league_metadata, period: str, exclude_ir: bool = False) -> LeagueSnapshot:
    from .weighted_coefficients import load_weighted_coefficients
    key = (period, exclude_ir, str(getattr(league_metadata, 'last_refresh_time', None)), tuple(sorted(load_weighted_coefficients().items())))
    cache = getattr(league_metadata, '_snapshot_cache', {})
    cached = cache.get(key)
    if cached and monotonic() - cached[0] < 30:
        return cached[1]
    raw_players = league_metadata.get_all_players_stats(
        period,
        "avg",
        exclude_ir=exclude_ir,
    )
    z_data = calculate_z_scores_from_players(raw_players)
    z_by_player = {
        (player["team_id"], player["name"]): player["z_scores"]
        for player in z_data["players"]
    }

    players = tuple(
        PlayerSnapshot(
            player_id=player.get("player_id"),
            name=player["name"],
            fantasy_team_id=player["team_id"],
            fantasy_team_name=player["team_name"],
            position=player["position"],
            eligible_slots=tuple(player.get("eligible_slots") or ()),
            lineup_slot=player.get("lineup_slot") or "",
            injured=bool(player.get("injured")),
            injury_status=player.get("injury_status") or "ACTIVE",
            pro_team=player.get("pro_team"),
            schedule=player.get("schedule") or {},
            stats=player["stats"],
            z_scores=z_by_player.get((player["team_id"], player["name"]), {}),
            expected_return_date=player.get('expected_return_date'),
        )
        for player in raw_players
    )

    league = league_metadata.league
    snapshot = LeagueSnapshot(
        period=period,
        created_at=datetime.now(timezone.utc),
        current_matchup_period=int(league.currentMatchupPeriod),
        current_scoring_period=int(league.current_week),
        players=players,
        league_metrics=z_data["league_metrics"],
        active_slots=league_slots(league_metadata),
    )
    if len(cache) >= 12:
        cache.clear()
    cache[key] = (monotonic(), snapshot)
    league_metadata._snapshot_cache = cache
    return snapshot
