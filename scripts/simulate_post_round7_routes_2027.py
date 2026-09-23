"""Compare realistic post-round-7 routes for the user's 13-team punt build."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from itertools import combinations
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
PICKS = tuple(snake_pick_numbers(HERO_SLOT, TEAM_COUNT, ROUNDS))
POWER_RUNS = 36
ROUTE_RUNS = 1200

fixed.TEAM_COUNT = TEAM_COUNT
fixed.ROUNDS = ROUNDS
fixed.HERO_SLOT = HERO_SLOT

CORE_CLAXTON = (
    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
    "Josh Hart", "Nic Claxton", "Ausar Thompson",
)
CORE_CLINGAN = tuple("Donovan Clingan" if name == "Nic Claxton" else name for name in CORE_CLAXTON)

POOL = (
    "Isaiah Hartenstein", "Cason Wallace", "Peyton Watson", "Davion Mitchell",
    "Tre Jones", "Collin Murray-Boyles", "Tari Eason", "Toumani Camara",
    "Draymond Green",
)

# Cross-source central prices. Davion is moved materially earlier to model a room
# that knows his role and intends to target him.
SHARP_PRICES = {
    "Isaiah Hartenstein": 105.0,
    "Davion Mitchell": 110.0,
    "Cason Wallace": 121.0,
    "Collin Murray-Boyles": 123.5,
    "Peyton Watson": 124.0,
    "Toumani Camara": 121.0,
    "Tari Eason": 137.0,
    "Tre Jones": 150.0,
}

ROUTES = {
    "hartenstein100_davion109_cason126_peyton135_tre152": (
        "Isaiah Hartenstein", "Davion Mitchell", "Cason Wallace",
        "Peyton Watson", "Tre Jones", "Collin Murray-Boyles",
    ),
    "davion100_hartenstein109_cason126_peyton135_tre152": (
        "Davion Mitchell", "Isaiah Hartenstein", "Cason Wallace",
        "Peyton Watson", "Tre Jones", "Collin Murray-Boyles",
    ),
    "hartenstein100_davion109_peyton126_cason135_tre152": (
        "Isaiah Hartenstein", "Davion Mitchell", "Peyton Watson",
        "Cason Wallace", "Tre Jones", "Collin Murray-Boyles",
    ),
    "hartenstein100_davion109_cmb126_peyton135_tre152": (
        "Isaiah Hartenstein", "Davion Mitchell", "Collin Murray-Boyles",
        "Peyton Watson", "Tre Jones", "Cason Wallace",
    ),
}

OUTPUT = ROOT / "artifacts" / "analysis" / "post-round7-routes-2027.json"


def load_players():
    metadata = LeagueMetadata(fixed.LEAGUE_ID, fixed.SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, fixed.TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], fixed.CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
        if player["name"] in SHARP_PRICES:
            player["espn_market_pick"] = SHARP_PRICES[player["name"]]
    return players


def power_grid(players, core):
    required = {"Davion Mitchell", "Tre Jones"}
    candidates = [combo for combo in combinations(POOL, 6) if required.issubset(combo)]
    outcomes = {combo: [] for combo in candidates}
    for run in range(POWER_RUNS):
        market, _ = _scenario(players, 8_700_000, run)
        for combo in candidates:
            roster = (*core, *combo)
            rosters = fixed.draft_opponents(players, roster, market)
            stressed = stress_rosters(rosters, 8_800_000 + run)
            outcomes[combo].append(evaluate_projected_rosters(stressed, HERO_SLOT, fixed.CATEGORIES))
    rows = []
    for combo, values in outcomes.items():
        row = summarize(values)
        rows.append({"added": list(combo), **row})
    rows.sort(key=lambda row: (row["matchup_win_rate"], row["top_four_rate"], row["title_proxy_top6"]), reverse=True)
    return rows


def route_availability(players, route):
    by_name = {player["name"]: player for player in players}
    hits = Counter()
    exact = 0
    for run in range(ROUTE_RUNS):
        market, _ = _scenario(players, 8_900_000, run)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda item: item[1])]
        hero_index = 0
        complete = True
        full_route = (*CORE_CLAXTON, *route)
        for overall in range(1, TEAM_COUNT * ROUNDS + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT:
                target_name = full_route[hero_index]
                hero_index += 1
                target_id = _identity(by_name[target_name])
                if target_id in remaining:
                    selected = remaining[target_id]
                    hits[(overall, target_name)] += 1
                else:
                    complete = False
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
        exact += int(complete)
    return {
        "exact_rate": round(exact / ROUTE_RUNS * 100, 1),
        "picks": [
            {"pick": pick, "player": name, "available": round(hits[(pick, name)] / ROUTE_RUNS * 100, 1)}
            for pick, name in zip(PICKS[7:], route)
        ],
    }


def clingan_at_74(players):
    by_name = {player["name"]: player for player in players}
    hits = 0
    for run in range(ROUTE_RUNS):
        market, _ = _scenario(players, 9_074_000, run)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda item: item[1])]
        core_before = CORE_CLAXTON[:5]
        hero_index = 0
        for overall in range(1, PICKS[5] + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if overall == PICKS[5]:
                hits += int(_identity(by_name["Donovan Clingan"]) in remaining)
                break
            if slot == HERO_SLOT:
                target = by_name[core_before[hero_index]]
                hero_index += 1
                selected = remaining.get(_identity(target)) or first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
    return round(hits / ROUTE_RUNS * 100, 1)


def main():
    players = load_players()
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "picks": list(PICKS),
        "sharp_prices": SHARP_PRICES,
        "clingan_available_at_74": clingan_at_74(players),
        "claxton_power": power_grid(players, CORE_CLAXTON)[:12],
        "clingan_power": power_grid(players, CORE_CLINGAN)[:6],
        "routes": {name: route_availability(players, route) for name, route in ROUTES.items()},
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
