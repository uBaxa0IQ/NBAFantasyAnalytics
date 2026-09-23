"""Stress-test one-for-one contingency options for picks 24, 33 and 52."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from scripts.simulate_fixed_roster_2027 import (
    CATEGORIES, HERO_SLOT, LEAGUE_ID, SEASON, TEAM_ID,
    draft_opponents, stress_rosters, summarize,
)
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import _scenario, prepare_benchmark_market
from web.backend.services.draft_evaluation import evaluate_projected_rosters


RUNS = 110
BASE = (
    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
    "Josh Hart", "Ausar Thompson", "Nic Claxton", "Cason Wallace",
    "Isaiah Hartenstein", "Jalen Suggs", "Davion Mitchell",
    "Moussa Diabate", "Tre Jones",
)
GROUPS = {
    "pick24_giddey": (
        "Josh Giddey", "Amen Thompson", "Alperen Sengun", "Jalen Duren", "Evan Mobley",
    ),
    "pick33_chet": (
        "Chet Holmgren", "Evan Mobley", "Alperen Sengun", "Jalen Duren", "Donovan Clingan",
    ),
    "pick52_gobert": (
        "Rudy Gobert", "Jarrett Allen", "Donovan Clingan", "Walker Kessler",
        "Onyeka Okongwu", "Ivica Zubac",
    ),
}
OUTPUT = ROOT / "artifacts" / "analysis" / "top4-contingencies-2027.json"


def roster_variant(replaced, candidate):
    return tuple(candidate if name == replaced else name for name in BASE)


def run():
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    names = {player["name"] for player in players}
    required = set(BASE) | {name for group in GROUPS.values() for name in group}
    if missing := sorted(required - names):
        raise ValueError(f"Missing players: {missing}")

    outcomes = {
        group: {candidate: [] for candidate in candidates}
        for group, candidates in GROUPS.items()
    }
    for index in range(RUNS):
        market, _ = _scenario(players, 4_052_052, index)
        for group, candidates in GROUPS.items():
            replaced = candidates[0]
            for candidate in candidates:
                rosters = draft_opponents(players, roster_variant(replaced, candidate), market)
                stressed = stress_rosters(rosters, 70_000 + index)
                outcomes[group][candidate].append(
                    evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES)
                )

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_variant": RUNS,
        "base_roster": list(BASE),
        "groups": {
            group: {candidate: summarize(rows) for candidate, rows in candidates.items()}
            for group, candidates in outcomes.items()
        },
        "projection_source": recs.get("stats_source"),
        "market_source": recs.get("market_source"),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = run()
    print(json.dumps({"output": str(OUTPUT), "groups": data["groups"]}, ensure_ascii=False, indent=2))
