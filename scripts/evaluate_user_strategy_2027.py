"""Evaluate the proposed four-category punt for the main 2027 ESPN league."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from web.backend.services.draft import _draft_roster_slots, get_draft_recommendations
from web.backend.services.draft_benchmark import (
    _draft_once,
    _population_profiles,
    _scenario,
    _summarize,
    prepare_benchmark_market,
)
from web.backend.services.draft_simulation import _market_position


LEAGUE_ID = 203950642
SEASON = 2027
TEAM_ID = 12
HERO_SLOT = 5
CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")
ROUNDS = 13
PICKS = (5, 24, 33, 52, 61, 80, 89, 108, 117, 136, 145, 164, 173)
OUTPUT = ROOT / "artifacts/analysis/user-four-punt-2027.json"


def evaluate(runs: int = 160) -> dict:
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to the main ESPN league")
    recommendations = get_draft_recommendations(
        metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True
    )
    slots = tuple(_draft_roster_slots(metadata))[:ROUNDS]
    if len(slots) != ROUNDS:
        raise ValueError(f"Expected {ROUNDS} draftable roster slots, got {len(slots)}")
    players = prepare_benchmark_market(recommendations["players"], CATEGORIES, "espn_draft")
    players = [
        player for player in players
        if _market_position(player) is not None or player.get("espn_roto_rank") is not None
    ]
    opponents = _population_profiles(14, CATEGORIES, "human")
    strategies = (
        {"id": "requested_four_punt", "policy": "model", "punts": ("FT%", "3PM", "3PT%", "PTS")},
        {"id": "punt_stl_blk", "policy": "model", "punts": ("STL", "BLK")},
        {"id": "punt_pts", "policy": "model", "punts": ("PTS",)},
        {"id": "balanced", "policy": "model", "punts": ()},
    )
    outcomes = {strategy["id"]: [] for strategy in strategies}
    for run in range(runs):
        market, opponent_rank = _scenario(players, 2_027_092, run)
        for strategy in strategies:
            outcomes[strategy["id"]].append(
                _draft_once(
                    players, HERO_SLOT, 14, len(slots), strategy, market, opponent_rank,
                    slots, CATEGORIES, include_roster=True, opponent_profiles=opponents,
                    evaluation_noise_seed=f"user-four-punt:{run}",
                )
            )
    results = {}
    for strategy in strategies:
        drafts = outcomes[strategy["id"]]
        core = Counter()
        by_round = [Counter() for _ in slots]
        for draft in drafts:
            for index, player in enumerate(draft["roster"]):
                core[player["name"]] += 1
                by_round[index][player["name"]] += 1
        results[strategy["id"]] = {
            "punts": list(strategy["punts"]),
            "summary": _summarize(drafts, 14, CATEGORIES),
            "core": [{"name": name, "rate": round(count / runs, 3)} for name, count in core.most_common(20)],
            "rounds": [
                {
                    "round": index + 1,
                    "pick": PICKS[index],
                    "targets": [
                        {"name": name, "rate": round(count / runs, 3)}
                        for name, count in counter.most_common(6)
                    ],
                }
                for index, counter in enumerate(by_round)
            ],
        }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs": runs,
        "market_source": recommendations.get("market_source"),
        "projection_source": recommendations.get("stats_source"),
        "roster_slots": list(slots),
        "results": results,
    }


if __name__ == "__main__":
    payload = evaluate()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)
