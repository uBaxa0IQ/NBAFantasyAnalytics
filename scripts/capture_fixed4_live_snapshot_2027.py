"""Capture a dated, immutable live ESPN league snapshot for the fixed-punt audit."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft import get_draft_recommendations

OUTPUT = ROOT / "artifacts/analysis/main-league-2027-live-20260927.json"


def run():
    if OUTPUT.exists():
        return json.loads(OUTPUT.read_text(encoding="utf-8"))
    metadata = LeagueMetadata(203950642, 2027, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to target ESPN league")
    recommendations = get_draft_recommendations(
        metadata, 12, "2027_projected", (), 300, (), None, False, True)
    if recommendations.get("stats_source") != "selected_period":
        raise ValueError("ESPN 2027 projected stats unavailable; refusing fallback")
    players = recommendations.get("players") or []
    required = {"Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Josh Hart"}
    if len(players) < 200 or required - {player.get("name") for player in players}:
        raise ValueError("Incomplete live ESPN player pool")
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "league_id": 203950642, "season": 2027, "period": "2027_projected",
        "stats_source": recommendations["stats_source"],
        "market_source": recommendations.get("market_source"),
        "team_count": 14, "rounds": 13,
        "players": players,
    }
    save(OUTPUT, result)
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps({"output": str(OUTPUT), "created_at": result["created_at"],
                      "players": len(result["players"]),
                      "stats_source": result["stats_source"],
                      "market_source": result["market_source"]}, indent=2))
