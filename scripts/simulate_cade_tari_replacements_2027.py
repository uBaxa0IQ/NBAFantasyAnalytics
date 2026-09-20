"""Compare realistic pick-164 replacements for Tari Eason in the fixed Cade build."""
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
    CATEGORIES, CORE, HERO_SLOT, LEAGUE_ID, SEASON, TEAM_ID,
    draft_opponents, stress_rosters, summarize,
)
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import _scenario, prepare_benchmark_market
from web.backend.services.draft_evaluation import evaluate_projected_rosters
from web.backend.services.draft_simulation import _market_position


RUNS = 300
CANDIDATES = (
    "Tari Eason", "Jamal Shead", "Moussa Diabate", "Bobby Portis",
    "Jusuf Nurkic", "Deandre Ayton", "Khaman Maluach", "Morez Johnson Jr.",
    "Santi Aldama", "Jonathan Kuminga", "P.J. Washington",
)
OUTPUT = ROOT / "artifacts" / "analysis" / "cade-tari-replacements-2027.json"


def run():
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    by_name = {player["name"]: player for player in players}
    missing = sorted(set(CANDIDATES) - set(by_name))
    if missing:
        raise ValueError(f"Missing candidates: {missing}")

    base_core = tuple(name for name in CORE if name != "Tari Eason")
    outcomes = {name: [] for name in CANDIDATES}
    for run_index in range(RUNS):
        market, _ = _scenario(players, 9_822_164, run_index)
        for candidate in CANDIDATES:
            fixed = ("Cade Cunningham", *base_core, candidate)
            rosters = draft_opponents(players, fixed, market)
            stressed = stress_rosters(rosters, 20_000 + run_index)
            outcomes[candidate].append(evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES))

    rows = []
    for candidate in CANDIDATES:
        player = by_name[candidate]
        stats = player.get("stats") or {}
        rows.append({
            "name": candidate,
            "market_pick": round(float(_market_position(player) or 220.0), 2),
            "position": player.get("position"),
            "gp": stats.get("GP"),
            "fg_pct": round(float(stats.get("FG%", 0)) * 100, 1),
            "reb": round(float(stats.get("REB", 0)), 1),
            "ast": round(float(stats.get("AST", 0)), 1),
            "stl": round(float(stats.get("STL", 0)), 1),
            "blk": round(float(stats.get("BLK", 0)), 1),
            **summarize(outcomes[candidate]),
        })
    rows.sort(key=lambda row: (row["matchup_win_rate"], row["top_four_rate"]), reverse=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_candidate": RUNS,
        "first_pick": "Cade Cunningham",
        "replaced": "Tari Eason",
        "results": rows,
        "projection_source": recs.get("stats_source"),
        "market_source": recs.get("market_source"),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = run()
    print(json.dumps({"output": str(OUTPUT), "results": data["results"]}, ensure_ascii=False, indent=2))
