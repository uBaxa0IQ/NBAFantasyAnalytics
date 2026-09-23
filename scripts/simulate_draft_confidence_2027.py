"""14-team slot-5 confidence check for the current punt roster.

Opponents draft from a category-room board. Public ADPs are pulled forward
where the internal blend lets centers fall, so matchup rates are not inflated
by bigs that a real room would already have taken.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import fmean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from scripts.simulate_fixed_roster_2027 import (
    CATEGORIES, HERO_SLOT, LEAGUE_ID, SEASON, TEAM_ID, first_feasible,
)
import scripts.simulate_fixed_roster_2027 as fixed
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import _identity, _scenario, prepare_benchmark_market
from web.backend.services.draft_evaluation import evaluate_projected_rosters
from web.backend.services.draft_simulation import _slot_at_pick, snake_pick_numbers


TEAM_COUNT = 14
ROUNDS = 13
RUNS = 64
AVAIL_RUNS = 700
fixed.TEAM_COUNT = TEAM_COUNT
fixed.ROUNDS = ROUNDS
fixed.HERO_SLOT = HERO_SLOT
PICKS = tuple(snake_pick_numbers(HERO_SLOT, TEAM_COUNT, ROUNDS))
TARGET_CATS = ("FG%", "REB", "AST", "A/TO", "STL", "BLK", "DD")

# Earlier of the public prices a 14-team category room actually pays.
SHARP = {
    "Cade Cunningham": 8,
    "Amen Thompson": 20,
    "Alperen Sengun": 21,
    "Josh Giddey": 24,
    "Scottie Barnes": 27,
    "Chet Holmgren": 28,
    "Evan Mobley": 24,
    "Jalen Johnson": 30,
    "Bam Adebayo": 30,
    "Domantas Sabonis": 31,
    "Jalen Duren": 36,
    "Walker Kessler": 38,
    "Dyson Daniels": 42,
    "Rudy Gobert": 58,
    "Josh Hart": 70,
    "Ausar Thompson": 82,
    "Isaiah Hartenstein": 90,
    "Kel'el Ware": 100,
    "Donovan Clingan": 99,
    "Nic Claxton": 104,
    "Draymond Green": 108,
    "Toumani Camara": 112,
    "Peyton Watson": 112,
    "Jalen Suggs": 114,
    "Cason Wallace": 115,
    "Tari Eason": 124,
    "Aaron Nesmith": 134,
    "Herb Jones": 135,
    "Luguentz Dort": 150,
    "Davion Mitchell": 140,
    "Alex Caruso": 155,
    "Collin Murray-Boyles": 150,
    "Tre Jones": 165,
}

BASE = (
    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
    "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
    "Isaiah Hartenstein", "Peyton Watson", "Davion Mitchell",
    "Collin Murray-Boyles", "Tre Jones",
)
THIRDS = (
    "Chet Holmgren", "Evan Mobley", "Bam Adebayo", "Walker Kessler",
    "Jalen Duren", "Dyson Daniels", "Domantas Sabonis", "Alperen Sengun",
)
WINGS = (
    "Peyton Watson", "Toumani Camara", "Tari Eason", "Herb Jones",
    "Jalen Suggs", "Aaron Nesmith", "Luguentz Dort", "Alex Caruso",
)
BIG_REPLACEMENTS = (
    "Isaiah Hartenstein", "Kel'el Ware", "Donovan Clingan", "Day'Ron Sharpe", "Draymond Green",
)
ORDER = BASE
ORDER_DAVION = (
    "Cade Cunningham", "Josh Giddey", "Chet Holmgren", "Rudy Gobert",
    "Josh Hart", "Ausar Thompson", "Cason Wallace", "Nic Claxton",
    "Isaiah Hartenstein", "Davion Mitchell", "Peyton Watson",
    "Collin Murray-Boyles", "Tre Jones",
)
OUTPUT = ROOT / "artifacts" / "analysis" / "draft-confidence-2027.json"


def apply_sharp(players):
    by_name = {player["name"]: player for player in players}
    for name, price in SHARP.items():
        player = by_name.get(name)
        if player is None:
            continue
        current = player.get("espn_market_pick")
        player["espn_market_pick_raw"] = current
        if current is None:
            player["espn_market_pick"] = float(price)
        else:
            player["espn_market_pick"] = min(float(current), float(price))
    return by_name


def variant(replaced, candidate):
    roster = tuple(candidate if name == replaced else name for name in BASE)
    if len(set(roster)) != len(roster):
        return None
    return roster


def confidence(outcomes):
    def pct(key):
        return round(fmean(row[key] for row in outcomes) * 100, 1)

    ranks = [row["league_rank"] for row in outcomes]
    return {
        "beat_opponents_6plus": pct("matchup_win_rate"),
        "beat_opponents_7plus": pct("decisive_matchup_win_rate"),
        "beat_opponents_exactly_6": pct("narrow_matchup_win_rate"),
        "lose_to_opponents": pct("matchup_loss_rate"),
        "seasons_beating_10_of_13": round(sum(row["matchup_win_rate"] >= 10 / 13 for row in outcomes) / len(outcomes) * 100, 1),
        "seasons_beating_half": round(sum(row["matchup_win_rate"] >= 0.5 for row in outcomes) / len(outcomes) * 100, 1),
        "top4_rate": round(sum(rank <= 4 for rank in ranks) / len(ranks) * 100, 1),
        "avg_rank": round(fmean(ranks), 2),
        "avg_cats": round(fmean(row["average_matchup_score"] for row in outcomes), 2),
        "avg_worst_matchup": round(fmean(row["minimum_matchup_score"] for row in outcomes), 2),
        "target_cat_win": {
            cat: round(fmean(row["category_win_rate"][cat] for row in outcomes) * 100, 1)
            for cat in TARGET_CATS
        },
        "target_safety": {
            cat: round(fmean(row["category_margin_z"][cat] for row in outcomes), 2)
            for cat in TARGET_CATS
        },
    }


def evaluate_group(players, replaced, names):
    found = {player["name"] for player in players}
    outcomes = {}
    usable = []
    for name in names:
        roster = variant(replaced, name)
        if roster is None or any(player not in found for player in roster):
            continue
        usable.append(name)
        outcomes[name] = []
    for index in range(RUNS):
        market, _ = _scenario(players, 9_220_2027, index)
        for name in usable:
            rosters = fixed.draft_opponents(players, variant(replaced, name), market)
            stressed = fixed.stress_rosters(rosters, 330_000 + index)
            outcomes[name].append(evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES))
    return {name: confidence(rows) for name, rows in outcomes.items()}


def availability(players, order, runs, seed, price_overrides=None):
    by_name = {player["name"]: player for player in players}
    if price_overrides:
        for name, price in price_overrides.items():
            player = by_name.get(name)
            if player is not None:
                player["espn_market_pick"] = float(price)
    hits = Counter()
    for run_index in range(runs):
        market, _ = _scenario(players, seed, run_index)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        hero_round = 0
        for overall in range(1, TEAM_COUNT * ROUNDS + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT:
                wanted = by_name[order[hero_round]]
                hero_round += 1
                selected = remaining.get(_identity(wanted))
                if selected is None:
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
                else:
                    hits[wanted["name"]] += 1
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
    return [
        {"pick": PICKS[index], "name": name, "available": round(hits[name] / runs * 100, 1)}
        for index, name in enumerate(order)
    ]


def third_survival(players, names, runs=900):
    by_name = {player["name"]: player for player in players}
    hits = Counter()
    for run_index in range(runs):
        market, _ = _scenario(players, 4_433_2027, run_index)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        hero_round = 0
        for overall in range(1, PICKS[2] + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT and hero_round < 2:
                wanted = by_name[("Cade Cunningham", "Josh Giddey")[hero_round]]
                hero_round += 1
                selected = remaining.get(_identity(wanted)) or first_feasible(
                    board, remaining, rosters[slot], ROUNDS - len(rosters[slot])
                )
            elif overall == PICKS[2]:
                for name in names:
                    if _identity(by_name[name]) in remaining:
                        hits[name] += 1
                break
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
    return {name: round(hits[name] / runs * 100, 1) for name in names}


def market_rows(by_name, names):
    rows = []
    for name in names:
        player = by_name.get(name)
        if player is None:
            rows.append({"name": name, "missing": True})
            continue
        rows.append({
            "name": name,
            "pos": player.get("position"),
            "team": player.get("proTeam") or player.get("pro_team") or player.get("team"),
            "raw_market": player.get("espn_market_pick_raw", player.get("espn_market_pick")),
            "sharp_market": player.get("espn_market_pick"),
            "espn_adp": player.get("espn_adp"),
            "roto": player.get("espn_roto_rank"),
        })
    return rows


def run():
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 320, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    watched = list(dict.fromkeys([*BASE, *THIRDS, *WINGS, *BIG_REPLACEMENTS, "Amen Thompson", "Scottie Barnes"]))
    raw_snapshot = {
        player["name"]: {
            "market": player.get("espn_market_pick"),
            "adp": player.get("espn_adp"),
            "roto": player.get("espn_roto_rank"),
        }
        for player in players if player["name"] in set(watched)
    }
    by_name = apply_sharp(players)
    missing = sorted(set(BASE) - set(by_name))
    if missing:
        raise ValueError(f"Missing core players: {missing}")

    thirds = evaluate_group(players, "Chet Holmgren", THIRDS)
    wings = evaluate_group(players, "Peyton Watson", WINGS)
    bigs = evaluate_group(players, "Isaiah Hartenstein", BIG_REPLACEMENTS)
    present = [name for name in watched if name in by_name]
    sharp_avail = {
        "planned_order": availability(players, ORDER, AVAIL_RUNS, 6_136_2027),
        "davion_one_pick_earlier": availability(players, ORDER_DAVION, AVAIL_RUNS, 6_145_2027),
        "third_pick_survival": third_survival(players, [name for name in THIRDS if name in by_name]),
    }
    # League-aware Davion: room takes him ~15 spots before the public ESPN price.
    for name, price in (("Davion Mitchell", 125),):
        by_name[name]["espn_market_pick"] = float(price)
    aware = {
        "planned_davion_at_145": availability(players, ORDER, AVAIL_RUNS, 7_145_2027, {"Davion Mitchell": 125}),
        "davion_at_136": availability(players, ORDER_DAVION, AVAIL_RUNS, 7_136_2027, {"Davion Mitchell": 125}),
    }
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "team_count": TEAM_COUNT,
        "picks": list(PICKS),
        "runs": RUNS,
        "availability_runs": AVAIL_RUNS,
        "raw_market": raw_snapshot,
        "board": market_rows(by_name, present),
        "third_pick": thirds,
        "peyton_replacements": wings,
        "hartenstein_replacements": bigs,
        "availability_sharp": sharp_avail,
        "availability_if_room_is_on_davion": aware,
        "notes": [
            "14 teams, slot 5, 13 rounds.",
            "beat_opponents_6plus is the share of rival rosters we beat by winning at least 6 categories.",
            "beat_opponents_7plus is the comfortable margin. exactly_6 is a 6-5 sweat.",
            "Opponent boards use the earlier of the internal market and a category-room price, so centers do not fall for free.",
            "This is stressed season volume against the other drafted rosters, not a week-by-week schedule.",
        ],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = run()
    brief = {
        "output": str(OUTPUT),
        "picks": result["picks"],
        "third_pick": result["third_pick"],
        "peyton_replacements": result["peyton_replacements"],
        "hartenstein_replacements": result["hartenstein_replacements"],
        "third_survival": result["availability_sharp"]["third_pick_survival"],
        "planned": result["availability_sharp"]["planned_order"],
        "davion_up": result["availability_sharp"]["davion_one_pick_earlier"],
        "davion_aware_145": result["availability_if_room_is_on_davion"]["planned_davion_at_145"],
        "davion_aware_136": result["availability_if_room_is_on_davion"]["davion_at_136"],
    }
    print(json.dumps(brief, ensure_ascii=False, indent=2))
