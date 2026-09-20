"""Reproducible slot-5 punt analysis for ESPN league 203950642 (read-only)."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft import _draft_roster_slots, get_draft_recommendations
from web.backend.services.draft_benchmark import (_comparison, _draft_once, _identity,
    _population_profiles, _scenario, _summarize, prepare_benchmark_market)
from web.backend.services.draft_simulation import _market_position

LEAGUE_ID = 203950642
SEASON = 2027
TEAM_ID = 12
HERO_SLOT = 5
ROUNDS = 13
CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")
OUTPUT = ROOT / "artifacts/analysis/main-league-2027-slot5-punts.json"


def strategy_id(punts):
    return "balanced" if not punts else "punt_" + "_".join(category.replace("%", "pct").replace("/", "_").lower() for category in punts)


def strategy_rows(max_punts=3):
    rows = []
    for count in range(max_punts + 1):
        for punts in combinations(CATEGORIES, count):
            rows.append({"id": strategy_id(punts), "label": "No punt" if not punts else "Punt " + " + ".join(punts),
                         "policy": "model", "punts": tuple(punts)})
    return rows


def roster_summary(outcomes, picks):
    overall = Counter(); by_round = [Counter() for _ in range(ROUNDS)]
    for outcome in outcomes:
        for index, player in enumerate(outcome.get("roster", ())):
            overall[player["name"]] += 1
            if index < len(by_round): by_round[index][player["name"]] += 1
    total = max(1, len(outcomes))
    return {
        "core_players": [{"name": name, "frequency": round(count / total, 3)} for name, count in overall.most_common(25)],
        "round_targets": [{"round": index + 1, "overall_pick": picks[index],
            "players": [{"name": name, "frequency": round(count / total, 3)} for name, count in counter.most_common(8)]}
            for index, counter in enumerate(by_round)],
    }


def simulate(players, strategies, runs, seed, roster_slots):
    outcomes = {strategy["id"]: [] for strategy in strategies}
    opponents = _population_profiles(14, CATEGORIES, "human")
    for run in range(runs):
        market, opponent_rank = _scenario(players, seed, run)
        for strategy in strategies:
            outcomes[strategy["id"]].append(_draft_once(players, HERO_SLOT, 14, ROUNDS, strategy,
                market, opponent_rank, roster_slots, CATEGORIES, include_roster=True,
                opponent_profiles=opponents, evaluation_noise_seed=f"main:{seed}:{run}"))
    return outcomes


def run(screening_runs=4, deep_runs=80, sensitivity_runs=40, finalists=14):
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league(): raise ConnectionError("Could not connect to main ESPN league")
    raw_draft = metadata.league.espn_request.get_league_draft()
    settings = raw_draft.get("settings", {}).get("draftSettings", {})
    order = settings.get("pickOrder") or []
    if len(metadata.get_teams()) != 14 or TEAM_ID not in order or order.index(TEAM_ID) + 1 != HERO_SLOT:
        raise ValueError("Main league draft order changed")
    recommendations = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    if recommendations.get("stats_source") != "selected_period": raise ValueError("Projection fallback detected")
    # ESPN still exposes the temporary four-bench setup.  The confirmed draft
    # format has 13 rounds, so model the final roster as three bench slots.
    roster_slots = tuple(_draft_roster_slots(metadata))
    if len(roster_slots) > ROUNDS:
        roster_slots = roster_slots[:ROUNDS]
    if len(roster_slots) != ROUNDS:
        raise ValueError(f"Expected {ROUNDS} draftable roster slots, got {len(roster_slots)}")
    primary = prepare_benchmark_market(recommendations["players"], CATEGORIES, "espn_draft")
    primary = [player for player in primary if _market_position(player) is not None or player.get("espn_roto_rank") is not None]
    synthetic = prepare_benchmark_market(recommendations["players"], CATEGORIES, "category_z")
    synthetic = [player for player in synthetic if _market_position(player) is not None or player.get("espn_roto_rank") is not None]
    strategies = strategy_rows(3)
    screening = simulate(primary, strategies, screening_runs, 2_027_120, roster_slots)
    ranked = sorted(strategies, key=lambda row: (
        _summarize(screening[row["id"]], 14, CATEGORIES)["average_category_wins"],
        -_summarize(screening[row["id"]], 14, CATEGORIES)["average_league_rank"]), reverse=True)
    selected = ranked[:finalists]
    balanced = next(row for row in strategies if row["id"] == "balanced")
    if balanced not in selected: selected.append(balanced)
    roto = {"id": "espn_roto", "label": "ESPN draft ROTO", "policy": "roto", "punts": ()}
    selected.append(roto)
    deep = simulate(primary, selected, deep_runs, 2_027_500, roster_slots)
    sensitivity = simulate(synthetic, selected, sensitivity_runs, 2_027_900, roster_slots)
    picks = [5, 24, 33, 52, 61, 80, 89, 108, 117, 136, 145, 164, 173]
    rows = []
    for strategy in selected:
        row = {"id": strategy["id"], "label": strategy["label"], "punt_categories": list(strategy["punts"]),
               "espn_market": _summarize(deep[strategy["id"]], 14, CATEGORIES),
               "category_z_market": _summarize(sensitivity[strategy["id"]], 14, CATEGORIES),
               **roster_summary(deep[strategy["id"]], picks)}
        rows.append(row)
    rows.sort(key=lambda row: (row["espn_market"]["average_category_wins"],
                               -row["espn_market"]["average_league_rank"]), reverse=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(), "league_id": LEAGUE_ID, "season": SEASON,
        "team_id": TEAM_ID, "draft_slot": HERO_SLOT, "draft_order": order, "picks": picks,
        "draft_date": settings.get("date"), "team_count": 14, "rounds": ROUNDS,
        "categories": list(CATEGORIES), "roster_slots": list(roster_slots),
        "projection_source": recommendations.get("stats_source"), "market_source": recommendations.get("market_source"),
        "player_count": len(primary), "league_player_rater_coverage": sum(bool(p.get("market_category_match")) for p in primary),
        "strategies_screened": len(strategies), "screening_runs": screening_runs,
        "deep_runs": deep_runs, "sensitivity_runs": sensitivity_runs,
        "opponents": "alternating ESPN ROTO and ADP with stochastic boards",
        "evaluation": "projected volume with GP and per-game stress",
        "strategies": rows,
        "comparisons_to_balanced": [_comparison(row["id"], "balanced", deep) for row in selected if row["id"] != "balanced"],
        "comparisons_to_espn_roto": [_comparison(row["id"], "espn_roto", deep) for row in selected if row["id"] != "espn_roto"],
        "limitations": ["ESPN 2027 league Player Rater is not populated yet; current market uses draft ROTO plus ADP.",
                        "This is projected-season volume, not a weekly H2H schedule simulation.",
                        "Human reaches and punt choices remain uncertain before live draft data exists."],
    }
    save(OUTPUT, payload); return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    parser.add_argument("--screening-runs", type=int, default=4); parser.add_argument("--deep-runs", type=int, default=80)
    parser.add_argument("--sensitivity-runs", type=int, default=40); args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "PREPARED_NOT_STARTED", "strategies": 232,
            "screening_drafts": 232 * args.screening_runs,
            "deep_drafts_estimate": 16 * args.deep_runs,
            "sensitivity_drafts_estimate": 16 * args.sensitivity_runs,
            "output": str(OUTPUT)}, indent=2))
    else:
        result = run(args.screening_runs, args.deep_runs, args.sensitivity_runs)
        print(json.dumps({"status": "COMPLETE", "output": str(OUTPUT),
            "top": [{"label": row["label"], **row["espn_market"]} for row in result["strategies"][:10]]},
            ensure_ascii=False, indent=2))
