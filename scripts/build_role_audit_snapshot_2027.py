"""Export projected stat lines for every player in the live contingency tree."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import prepare_benchmark_market
from web.backend.services.draft_simulation import _market_position


CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")
NAMES = (
    "Nikola Jokic", "Victor Wembanyama", "Shai Gilgeous-Alexander", "Luka Doncic",
    "Cade Cunningham", "Jalen Johnson", "Giannis Antetokounmpo", "Tyrese Haliburton",
    "Josh Giddey", "Chet Holmgren", "Rudy Gobert", "Josh Hart", "Ausar Thompson",
    "Nic Claxton", "Cason Wallace", "Isaiah Hartenstein", "Jalen Suggs",
    "Peyton Watson", "Davion Mitchell", "Moussa Diabate", "Tre Jones", "Alperen Sengun",
    "Evan Mobley", "Jalen Duren", "Donovan Clingan", "Jarrett Allen", "Walker Kessler",
    "Deni Avdija", "OG Anunoby", "VJ Edgecombe", "Collin Murray-Boyles",
    "Toumani Camara", "Draymond Green", "Tari Eason", "Kel'el Ware", "Day'Ron Sharpe", "Ajay Mitchell", "Ayo Dosunmu",
    "Scotty Pippen Jr.", "Jakob Poeltl", "Oso Ighodaro", "Alex Caruso", "Jrue Holiday",
    "T.J. McConnell", "Jusuf Nurkic", "Yves Missi", "Robert Williams III",
    "Deandre Ayton", "Jamal Shead",
)
OUTPUT = ROOT / "artifacts" / "analysis" / "role-audit-snapshot-2027.json"


def run():
    metadata = LeagueMetadata(203950642, 2027, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, 12, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    by_name = {player["name"]: player for player in players}
    rows = []
    for name in NAMES:
        player = by_name.get(name)
        if not player:
            rows.append({"name": name, "missing": True})
            continue
        stats = player.get("stats") or {}
        rows.append({
            "name": name,
            "team": player.get("team"),
            "position": player.get("position"),
            "market_pick": round(float(_market_position(player) or 220.0), 1),
            "GP": stats.get("GP"),
            "PTS": round(float(stats.get("PTS", 0)), 1),
            "FG%": round(float(stats.get("FG%", 0)) * 100, 1),
            "REB": round(float(stats.get("REB", 0)), 1),
            "AST": round(float(stats.get("AST", 0)), 1),
            "A/TO": round(float(stats.get("A/TO", 0)), 2),
            "STL": round(float(stats.get("STL", 0)), 1),
            "BLK": round(float(stats.get("BLK", 0)), 1),
            "DD": round(float(stats.get("DD", 0)), 1),
        })
    payload = {
        "projection_source": recs.get("stats_source"),
        "market_source": recs.get("market_source"),
        "players": rows,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
