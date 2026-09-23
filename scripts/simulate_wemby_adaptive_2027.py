"""Test Wembanyama-specific roster pivots rather than forcing the Cade core."""
from __future__ import annotations

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


RUNS = 100
TAIL = (
    "Josh Hart", "Ausar Thompson", "Nic Claxton", "Cason Wallace",
    "Isaiah Hartenstein", "Jalen Suggs", "Davion Mitchell",
    "Moussa Diabate", "Tre Jones",
)
VARIANTS = {
    "fixed_chet_gobert": (
        "Victor Wembanyama", "Josh Giddey", "Chet Holmgren", "Rudy Gobert", *TAIL,
    ),
    "adaptive_sengun_deni": (
        "Victor Wembanyama", "Josh Giddey", "Alperen Sengun", "Deni Avdija", *TAIL,
    ),
    "adaptive_duren_deni": (
        "Victor Wembanyama", "Josh Giddey", "Jalen Duren", "Deni Avdija", *TAIL,
    ),
}
OUTPUT = ROOT / "artifacts" / "analysis" / "wemby-adaptive-2027.json"


def run():
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    outcomes = {name: [] for name in VARIANTS}
    for index in range(RUNS):
        market, _ = _scenario(players, 4_052_005, index)
        for name, roster in VARIANTS.items():
            rosters = draft_opponents(players, roster, market)
            stressed = stress_rosters(rosters, 120_000 + index)
            outcomes[name].append(evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES))
    payload = {
        "runs_per_variant": RUNS,
        "variants": {name: summarize(rows) for name, rows in outcomes.items()},
        "rosters": {name: list(roster) for name, roster in VARIANTS.items()},
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = run()
    print(json.dumps({"output": str(OUTPUT), **data}, ensure_ascii=False, indent=2))
