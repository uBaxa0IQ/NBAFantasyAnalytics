"""H2H-majority audit for a requested punt in the main 2027 ESPN league."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import fmean, pstdev
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from scripts.run_v74_resilient import resilient_json as save
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
TEAM_COUNT = 14
ROUNDS = 13
CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")
OUTPUT = ROOT / "artifacts/analysis/main-league-2027-specific-punt-h2h.json"


STRATEGIES = (
    {"id": "punt_ft_3pm_3pt", "label": "Punt FT% + 3PM + 3PT%", "policy": "model", "punts": ("FT%", "3PM", "3PT%")},
    {"id": "punt_reb_blk", "label": "Punt REB + BLK", "policy": "model", "punts": ("REB", "BLK")},
    {"id": "punt_stl_blk", "label": "Punt STL + BLK", "policy": "model", "punts": ("STL", "BLK")},
    {"id": "balanced", "label": "No punt", "policy": "model", "punts": ()},
    {"id": "espn_roto", "label": "ESPN draft ROTO", "policy": "roto", "punts": ()},
)


def interval(values):
    mean = fmean(values) if values else 0.0
    margin = 1.96 * pstdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return [round((mean - margin) * 100, 2), round((mean + margin) * 100, 2)]


def paired(candidate, baseline):
    win_rate = [left["matchup_win_rate"] - right["matchup_win_rate"] for left, right in zip(candidate, baseline)]
    decisive = [left["decisive_matchup_win_rate"] - right["decisive_matchup_win_rate"]
                for left, right in zip(candidate, baseline)]
    score = [left["average_matchup_score"] - right["average_matchup_score"]
             for left, right in zip(candidate, baseline)]
    return {
        "delta_matchup_win_rate_pp": round(fmean(win_rate) * 100, 2),
        "delta_matchup_win_rate_ci95_pp": interval(win_rate),
        "delta_decisive_win_rate_pp": round(fmean(decisive) * 100, 2),
        "delta_average_matchup_score": round(fmean(score), 3),
        "better_scenario_rate": round(sum(value > 1e-12 for value in win_rate) / len(win_rate) * 100, 1),
        "worse_scenario_rate": round(sum(value < -1e-12 for value in win_rate) / len(win_rate) * 100, 1),
    }


def run(runs=200):
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to main ESPN league")
    recommendations = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    if recommendations.get("stats_source") != "selected_period":
        raise ValueError("Projection fallback detected")
    slots = tuple(_draft_roster_slots(metadata))[:ROUNDS]
    if len(slots) != ROUNDS:
        raise ValueError(f"Expected {ROUNDS} roster slots, got {len(slots)}")
    players = prepare_benchmark_market(recommendations["players"], CATEGORIES, "espn_draft")
    players = [row for row in players if _market_position(row) is not None or row.get("espn_roto_rank") is not None]
    opponents = _population_profiles(TEAM_COUNT, CATEGORIES, "human")
    outcomes = {row["id"]: [] for row in STRATEGIES}
    rosters = {row["id"]: Counter() for row in STRATEGIES}
    for index in range(runs):
        market, opponent_rank = _scenario(players, 2_027_613, index)
        for strategy in STRATEGIES:
            result = _draft_once(
                players, HERO_SLOT, TEAM_COUNT, ROUNDS, strategy, market, opponent_rank,
                slots, CATEGORIES, include_roster=True, opponent_profiles=opponents,
                evaluation_noise_seed=f"specific-h2h:{index}",
            )
            outcomes[strategy["id"]].append(result)
            rosters[strategy["id"]].update(player["name"] for player in result["roster"])
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "league_id": LEAGUE_ID,
        "team_count": TEAM_COUNT,
        "rounds": ROUNDS,
        "draft_slot": HERO_SLOT,
        "categories": list(CATEGORIES),
        "runs": runs,
        "matchups_per_strategy": runs * (TEAM_COUNT - 1),
        "projection_source": recommendations.get("stats_source"),
        "market_source": recommendations.get("market_source"),
        "results": {
            strategy["id"]: {
                "label": strategy["label"],
                "punts": list(strategy["punts"]),
                **_summarize(outcomes[strategy["id"]], TEAM_COUNT, CATEGORIES),
                "core_players": [
                    {"name": name, "rate": round(count / runs * 100, 1)}
                    for name, count in rosters[strategy["id"]].most_common(18)
                ],
            }
            for strategy in STRATEGIES
        },
        "requested_vs_balanced": paired(outcomes["punt_ft_3pm_3pt"], outcomes["balanced"]),
        "requested_vs_reb_blk": paired(outcomes["punt_ft_3pm_3pt"], outcomes["punt_reb_blk"]),
        "reb_blk_vs_balanced": paired(outcomes["punt_reb_blk"], outcomes["balanced"]),
        "method": "Paired projected-roster H2H majority audit; a win requires at least 6 of 11 categories.",
        "limitations": [
            "Projected season-volume matchups with GP/stat uncertainty, not an NBA weekly schedule simulation.",
            "Opponent draft behavior is a synthetic ESPN ROTO/ADP mixture.",
        ],
    }
    save(OUTPUT, payload)
    return payload


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": "COMPLETE", "output": str(OUTPUT), "results": result["results"],
                      "requested_vs_balanced": result["requested_vs_balanced"],
                      "requested_vs_reb_blk": result["requested_vs_reb_blk"]}, ensure_ascii=False, indent=2))
