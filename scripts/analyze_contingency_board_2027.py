"""Compare first-round windfalls and expose a compact contingency player board."""
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
from web.backend.services.draft_simulation import _market_position


RUNS = 220
FIRST_PICKS = (
    "Nikola Jokic", "Victor Wembanyama", "Shai Gilgeous-Alexander",
    "Luka Doncic", "Cade Cunningham", "Jalen Johnson", "Tyrese Haliburton",
)
CORE = (
    "Josh Giddey", "Chet Holmgren", "Rudy Gobert", "Josh Hart",
    "Ausar Thompson", "Nic Claxton", "Cason Wallace", "Isaiah Hartenstein",
    "Jalen Suggs", "Davion Mitchell", "Moussa Diabate", "Tre Jones",
)
CANDIDATES = (
    # Early-round contingency names.
    "Amen Thompson", "Scottie Barnes", "Alperen Sengun", "Evan Mobley",
    "Jalen Duren", "Jarrett Allen", "Donovan Clingan", "Walker Kessler",
    "Ivica Zubac", "Onyeka Okongwu",
    # Middle and late contingency names.
    "OG Anunoby", "Deni Avdija", "Draymond Green", "Tari Eason",
    "Herb Jones", "Toumani Camara", "Kel'el Ware", "Zach Edey",
    "Jakob Poeltl", "Derik Queen", "Oso Ighodaro", "Scotty Pippen Jr.",
    "T.J. McConnell", "Alex Caruso", "Jrue Holiday", "Ryan Rollins",
    "Jamal Shead", "Ajay Mitchell", "Jusuf Nurkic", "Deandre Ayton",
    "Bobby Portis", "Morez Johnson Jr.", "Khaman Maluach",
)
OUTPUT = ROOT / "artifacts" / "analysis" / "draft-contingency-board-2027.json"


def compact_player(player):
    stats = player.get("stats") or {}
    return {
        "name": player["name"],
        "position": player.get("position"),
        "market_pick": round(float(_market_position(player) or 220.0), 2),
        "gp": stats.get("GP"),
        "fg_pct": round(float(stats.get("FG%", 0)) * 100, 1),
        "ft_pct": round(float(stats.get("FT%", 0)) * 100, 1),
        "reb": round(float(stats.get("REB", 0)), 1),
        "ast": round(float(stats.get("AST", 0)), 1),
        "ato": round(float(stats.get("A/TO", 0)), 2),
        "stl": round(float(stats.get("STL", 0)), 1),
        "blk": round(float(stats.get("BLK", 0)), 1),
        "dd": round(float(stats.get("DD", 0)), 1),
    }


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
    required = set(FIRST_PICKS) | set(CORE)
    if missing := sorted(required - set(by_name)):
        raise ValueError(f"Missing required players: {missing}")

    variants = {name: [] for name in FIRST_PICKS}
    for index in range(RUNS):
        market, _ = _scenario(players, 4_052_164, index)
        for first in FIRST_PICKS:
            rosters = draft_opponents(players, (first, *CORE), market)
            stressed = stress_rosters(rosters, 50_000 + index)
            variants[first].append(evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES))

    missing_candidates = sorted(set(CANDIDATES) - set(by_name))
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_variant": RUNS,
        "fixed_core": list(CORE),
        "first_pick_variants": {name: summarize(rows) for name, rows in variants.items()},
        "candidate_board": [compact_player(by_name[name]) for name in CANDIDATES if name in by_name],
        "missing_candidates": missing_candidates,
        "projection_source": recs.get("stats_source"),
        "market_source": recs.get("market_source"),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = run()
    print(json.dumps({
        "output": str(OUTPUT),
        "variants": data["first_pick_variants"],
        "candidate_board": data["candidate_board"],
        "missing_candidates": data["missing_candidates"],
    }, ensure_ascii=False, indent=2))
