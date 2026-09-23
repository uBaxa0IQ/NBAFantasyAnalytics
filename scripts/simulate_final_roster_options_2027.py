"""Evaluate the user's near-final 13-team punt roster and draft-order choices."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
import scripts.simulate_fixed_roster_2027 as fixed
from scripts.simulate_fixed_roster_2027 import first_feasible, stress_rosters, summarize
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import _identity, _scenario, prepare_benchmark_market
from web.backend.services.draft_evaluation import evaluate_projected_rosters
from web.backend.services.draft_simulation import _slot_at_pick, snake_pick_numbers


TEAM_COUNT = 13
ROUNDS = 13
HERO_SLOT = 5
RUNS = 90
AVAILABILITY_RUNS = 900
PICKS = tuple(snake_pick_numbers(HERO_SLOT, TEAM_COUNT, ROUNDS))

# The existing helpers read these globals from their source module.
fixed.TEAM_COUNT = TEAM_COUNT
fixed.ROUNDS = ROUNDS
fixed.HERO_SLOT = HERO_SLOT

THIRD_PICK = (
    "Domantas Sabonis", "Evan Mobley", "Jalen Duren", "Alperen Sengun", "Dyson Daniels", "Chet Holmgren",
    "Donovan Clingan", "Jarrett Allen", "Walker Kessler", "Onyeka Okongwu",
)
ROUND11_WINGS = (
    "Peyton Watson", "Toumani Camara", "Draymond Green", "Bobby Portis",
    "Tari Eason", "Collin Murray-Boyles", "Morez Johnson Jr.", "Precious Achiuwa",
)

BASE = (
    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
    "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
    "Isaiah Hartenstein", "Peyton Watson", "Davion Mitchell",
    "Collin Murray-Boyles", "Tre Jones",
)

ORDERS = {
    "claxton_first_old": (
        "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
        "Josh Hart", "Ausar Thompson", "Nic Claxton", "Isaiah Hartenstein",
        "Cason Wallace", "Davion Mitchell", "Peyton Watson",
        "Collin Murray-Boyles", "Tre Jones",
    ),
    "cason_first_user": (
        "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
        "Josh Hart", "Ausar Thompson", "Cason Wallace", "Isaiah Hartenstein",
        "Nic Claxton", "Davion Mitchell", "Peyton Watson",
        "Collin Murray-Boyles", "Tre Jones",
    ),
    "market_optimized": (
        "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
        "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
        "Isaiah Hartenstein", "Peyton Watson", "Davion Mitchell",
        "Collin Murray-Boyles", "Tre Jones",
    ),
    "davion_before_peyton": (
        "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
        "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
        "Isaiah Hartenstein", "Davion Mitchell", "Peyton Watson",
        "Collin Murray-Boyles", "Tre Jones",
    ),
    "peyton_protected": (
        "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
        "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
        "Peyton Watson", "Isaiah Hartenstein", "Davion Mitchell",
        "Collin Murray-Boyles", "Tre Jones",
    ),
}

OUTPUT = ROOT / "artifacts" / "analysis" / "final-roster-options-2027.json"


def variant(replaced: str, candidate: str):
    return tuple(candidate if name == replaced else name for name in BASE)


def availability(players, order):
    by_name = {player["name"]: player for player in players}
    hits = Counter()
    exact = 0
    for run in range(AVAILABILITY_RUNS):
        market, _ = _scenario(players, 8_426_013, run)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        completed = True
        hero_round = 0
        for overall in range(1, TEAM_COUNT * ROUNDS + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT:
                wanted_name = order[hero_round]
                hero_round += 1
                wanted = by_name[wanted_name]
                wanted_id = _identity(wanted)
                if wanted_id in remaining:
                    selected = remaining[wanted_id]
                    hits[wanted_name] += 1
                else:
                    completed = False
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
        exact += int(completed)
    return {
        "exact_roster_rate": round(exact / AVAILABILITY_RUNS * 100, 1),
        "by_round": [
            {"round": i + 1, "pick": PICKS[i], "name": name, "available": round(hits[name] / AVAILABILITY_RUNS * 100, 1)}
            for i, name in enumerate(order)
        ],
    }


def third_pick_availability(players, candidates, runs=1800):
    """Probability each candidate survives to pick 31 after we target Cade and Giddey."""
    by_name = {player["name"]: player for player in players}
    hits = Counter()
    for run_index in range(runs):
        market, _ = _scenario(players, 5_031_2027, run_index)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        hero_round = 0
        for overall in range(1, PICKS[2] + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT and hero_round < 2:
                wanted_name = ("Cade Cunningham", "Josh Giddey")[hero_round]
                hero_round += 1
                wanted_id = _identity(by_name[wanted_name])
                selected = remaining.get(wanted_id)
                if selected is None:
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            elif overall == PICKS[2]:
                for name in candidates:
                    if _identity(by_name[name]) in remaining:
                        hits[name] += 1
                break
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
    return {name: round(hits[name] / runs * 100, 1) for name in candidates}


def checkpoint_availability(players, candidates, checkpoint_pick, fixed_targets, runs=1400):
    """Availability of candidates at a checkpoint after selecting earlier fixed targets."""
    by_name = {player["name"]: player for player in players}
    hits = Counter()
    for run_index in range(runs):
        market, _ = _scenario(players, 5_057_2027, run_index)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        hero_round = 0
        for overall in range(1, checkpoint_pick + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if overall == checkpoint_pick:
                for name in candidates:
                    if _identity(by_name[name]) in remaining:
                        hits[name] += 1
                break
            if slot == HERO_SLOT and hero_round < len(fixed_targets):
                wanted_name = fixed_targets[hero_round]
                hero_round += 1
                wanted_id = _identity(by_name[wanted_name])
                selected = remaining.get(wanted_id)
                if selected is None:
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
    return {name: round(hits[name] / runs * 100, 1) for name in candidates}


def run():
    metadata = LeagueMetadata(fixed.LEAGUE_ID, fixed.SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, fixed.TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], fixed.CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    names = {p["name"] for p in players}
    required = set(BASE) | set(THIRD_PICK) | set(ROUND11_WINGS)
    if missing := sorted(required - names):
        raise ValueError(f"Missing players: {missing}")

    groups = {
        "third_pick": {name: [] for name in THIRD_PICK},
        "round11_wing": {name: [] for name in ROUND11_WINGS},
    }
    for run_index in range(RUNS):
        market, _ = _scenario(players, 3_031_2027, run_index)
        for candidate in THIRD_PICK:
            roster = variant("Chet Holmgren", candidate)
            rosters = fixed.draft_opponents(players, roster, market)
            stressed = stress_rosters(rosters, 110_000 + run_index)
            groups["third_pick"][candidate].append(evaluate_projected_rosters(stressed, HERO_SLOT, fixed.CATEGORIES))
        for candidate in ROUND11_WINGS:
            roster = variant("Peyton Watson", candidate)
            # CMB already occupies round 12; avoid a duplicate in this diagnostic.
            if len(set(roster)) != len(roster):
                continue
            rosters = fixed.draft_opponents(players, roster, market)
            stressed = stress_rosters(rosters, 220_000 + run_index)
            groups["round11_wing"][candidate].append(evaluate_projected_rosters(stressed, HERO_SLOT, fixed.CATEGORIES))

    by_name = {p["name"]: p for p in players}
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "team_count": TEAM_COUNT,
        "picks": list(PICKS),
        "runs_per_variant": RUNS,
        "groups": {
            group: {name: summarize(rows) for name, rows in candidates.items() if rows}
            for group, candidates in groups.items()
        },
        "market": {
            name: {
                "espn_market_pick": by_name[name].get("espn_market_pick"),
                "position": by_name[name].get("position"),
                "stats": by_name[name].get("stats"),
            }
            for name in required
        },
        "order_availability": {name: availability(players, order) for name, order in ORDERS.items()},
        "notes": [
            "13-team snake from slot 5: picks 5,22,31,48,57,74,83,100,109,126,135,152,161.",
            "Power simulations compare completed fixed rosters; order simulations measure market feasibility only.",
            "ESPN projections predate some September role news, so role-adjusted interpretation is required.",
        ],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--third-availability-only", action="store_true")
    parser.add_argument("--extra-third-power-only", action="store_true")
    parser.add_argument("--protected-order-only", action="store_true")
    parser.add_argument("--round5-big-power-only", action="store_true")
    parser.add_argument("--early-big-orders-only", action="store_true")
    args = parser.parse_args()
    if args.third_availability_only or args.extra_third_power_only or args.protected_order_only or args.round5_big_power_only or args.early_big_orders_only:
        metadata = LeagueMetadata(fixed.LEAGUE_ID, fixed.SEASON, ESPN_S2, SWID)
        if not metadata.connect_to_league():
            raise ConnectionError("Could not connect to ESPN league")
        recs = get_draft_recommendations(metadata, fixed.TEAM_ID, "2027_projected", (), 300, (), None, False, True)
        players = prepare_benchmark_market(recs["players"], fixed.CATEGORIES, "espn_draft")
        for player in players:
            if player.get("espn_market_pick") is None:
                player["espn_market_pick"] = 220.0
        if args.early_big_orders_only:
            early_orders = {
                "market_order": (
                    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
                    "Jarrett Allen", "Ausar Thompson", "Josh Hart", "Peyton Watson",
                    "Cason Wallace", "Isaiah Hartenstein", "Davion Mitchell",
                    "Collin Murray-Boyles", "Tre Jones",
                ),
                "hart_first": (
                    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
                    "Jarrett Allen", "Josh Hart", "Ausar Thompson", "Cason Wallace",
                    "Peyton Watson", "Isaiah Hartenstein", "Davion Mitchell",
                    "Collin Murray-Boyles", "Tre Jones",
                ),
            }
            print(json.dumps({
                "round5_candidates": checkpoint_availability(
                    players,
                    ("Jarrett Allen", "Donovan Clingan", "Walker Kessler"),
                    PICKS[4],
                    ("Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert"),
                ),
                "orders": {label: availability(players, order) for label, order in early_orders.items()},
            }, ensure_ascii=False, indent=2))
        elif args.round5_big_power_only:
            variants = {"baseline": BASE}
            for candidate in ("Walker Kessler", "Jarrett Allen", "Donovan Clingan"):
                variants[f"{candidate}_for_Hartenstein"] = tuple(candidate if name == "Isaiah Hartenstein" else name for name in BASE)
                variants[f"{candidate}_for_Claxton"] = tuple(candidate if name == "Nic Claxton" else name for name in BASE)
            output = {}
            for label, roster in variants.items():
                rows = []
                for run_index in range(RUNS):
                    market, _ = _scenario(players, 5_057_2027, run_index)
                    rosters = fixed.draft_opponents(players, roster, market)
                    stressed = stress_rosters(rosters, 330_000 + run_index)
                    rows.append(evaluate_projected_rosters(stressed, HERO_SLOT, fixed.CATEGORIES))
                output[label] = summarize(rows)
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif args.protected_order_only:
            print(json.dumps(availability(players, ORDERS["peyton_protected"]), ensure_ascii=False, indent=2))
        elif args.third_availability_only:
            print(json.dumps(third_pick_availability(players, THIRD_PICK), ensure_ascii=False, indent=2))
        else:
            output = {}
            for candidate in ("Domantas Sabonis", "Dyson Daniels"):
                rows = []
                for run_index in range(RUNS):
                    market, _ = _scenario(players, 3_031_2027, run_index)
                    roster = variant("Chet Holmgren", candidate)
                    rosters = fixed.draft_opponents(players, roster, market)
                    stressed = stress_rosters(rosters, 110_000 + run_index)
                    rows.append(evaluate_projected_rosters(stressed, HERO_SLOT, fixed.CATEGORIES))
                output[candidate] = summarize(rows)
            print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        result = run()
        print(json.dumps({
            "output": str(OUTPUT),
            "third_pick": result["groups"]["third_pick"],
            "round11_wing": result["groups"]["round11_wing"],
            "orders": result["order_availability"],
        }, ensure_ascii=False, indent=2))
