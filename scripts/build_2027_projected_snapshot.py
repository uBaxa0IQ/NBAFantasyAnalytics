"""Build one immutable, validated snapshot from ESPN 2027 projections."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import DEFAULT_TEAM_ID, PERIODS
from web.backend.dependencies import get_league_meta
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import prepare_players_for_categories
from web.backend.services.draft_ml.schema import categories_for_format
from web.backend.services.draft_ml.v7_state import STATS

OUTPUT = ROOT / "artifacts/draft_ml/2027-projected/standard8-2027-projected-v2.json"


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def validate(players):
    ids = set()
    for player in players:
        player_id = player.get("player_id")
        if player_id is None or player_id in ids:
            raise ValueError(f"Missing or duplicate player id: {player_id}")
        ids.add(player_id)
        stats = player.get("stats") or {}
        if any(key not in stats for key in STATS):
            raise ValueError(f"Incomplete projection: {player.get('name')}")
        if "DD" not in stats or not 0 <= float(stats["DD"]) <= 1:
            raise ValueError(f"Missing derived DD projection: {player.get('name')}")
        if any(not math.isfinite(float(stats[key])) or float(stats[key]) < 0 for key in STATS):
            raise ValueError(f"Invalid projection: {player.get('name')}")
        for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "3PA")):
            if float(stats[made]) > float(stats[attempted]) + 1e-9:
                raise ValueError(f"Impossible projection: {player.get('name')} {made}>{attempted}")


def build(output: Path):
    if output.exists():
        raise FileExistsError(f"Immutable snapshot already exists: {output}")
    get_league_meta.cache_clear()
    metadata = get_league_meta()
    if metadata.year != 2027 or PERIODS["projected"] != "2027_projected":
        raise ValueError("Refusing to build a mixed-season snapshot")
    team_id = DEFAULT_TEAM_ID
    if team_id is None:
        teams = metadata.get_teams()
        if not teams:
            raise ValueError("No ESPN team is available")
        team_id = teams[0].team_id
    recommendations = get_draft_recommendations(
        metadata, team_id, PERIODS["projected"], (), 300, (), None, False, True,
    )
    if recommendations.get("stats_source") != "selected_period":
        raise ValueError(f"Projection fallback detected: {recommendations.get('stats_source')}")
    if any(player.get("stats_source") != "selected_period" for player in recommendations["players"]):
        raise ValueError("Per-player projection fallback detected")
    categories = categories_for_format("standard8")
    players = prepare_players_for_categories(recommendations["players"], categories)
    validate(players)
    if len(players) < 250:
        raise ValueError(f"Projection pool is unexpectedly small: {len(players)}")
    payload = {
        "schema_version": 2,
        "players": players,
        "categories": list(categories),
        "roster_slots": recommendations.get("roster_slots"),
        "team_count": len(metadata.get_teams()),
        "rounds": recommendations.get("draft_rounds"),
        "league_id": metadata.league_id,
        "season": metadata.year,
        "period": PERIODS["projected"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stats_source": "selected_period",
        "previous_season_fallback": False,
        "player_count": len(players),
        "projected_dd_source_counts": recommendations.get("projected_dd_source_counts"),
        "projection_validation": "strict_core_sparse_zero_and_derived_dd_v2",
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    atomic_text(output, serialized)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    manifest = {
        "snapshot": str(output.relative_to(ROOT)),
        "sha256": digest,
        "season": 2027,
        "period": "2027_projected",
        "player_count": len(players),
        "stats_source": "selected_period",
        "projected_dd_source_counts": payload["projected_dd_source_counts"],
        "created_at": payload["created_at"],
    }
    atomic_text(output.with_suffix(".manifest.json"), json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "PREPARED_NOT_STARTED", "output": str(args.output)}, indent=2))
        return
    print(json.dumps(build(args.output.resolve()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
