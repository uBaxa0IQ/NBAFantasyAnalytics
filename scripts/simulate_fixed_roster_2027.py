"""Stress-test the user's fixed 13-player 2027 roster and first-pick variants."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import random
from pathlib import Path
from statistics import fmean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import ESPN_S2, SWID
from core.league_metadata import LeagueMetadata
from core.projection import can_play_slot
from web.backend.services.draft import get_draft_recommendations
from web.backend.services.draft_benchmark import _identity, _scenario, prepare_benchmark_market
from web.backend.services.draft_evaluation import evaluate_projected_rosters
from web.backend.services.draft_simulation import _slot_at_pick, snake_pick_numbers


LEAGUE_ID = 203950642
SEASON = 2027
TEAM_ID = 12
HERO_SLOT = 5
TEAM_COUNT = 14
ROUNDS = 13
RUNS = 600
FEASIBILITY_RUNS = 1800
CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")
ROSTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UT", "UT", "UT", "BE", "BE", "BE")
PICKS = tuple(snake_pick_numbers(HERO_SLOT, TEAM_COUNT, ROUNDS))
CORE = (
    "Josh Giddey", "Chet Holmgren", "Rudy Gobert", "Josh Hart", "Ausar Thompson",
    "Nic Claxton", "Cason Wallace", "Isaiah Hartenstein", "Jalen Suggs",
    "Davion Mitchell", "Tari Eason", "Tre Jones",
)
FIRST_PICKS = (
    "Cade Cunningham", "Jalen Johnson", "Scottie Barnes",
    "Tyrese Haliburton", "Giannis Antetokounmpo",
)
OUTPUT = ROOT / "artifacts" / "analysis" / "fixed-roster-first-pick-2027.json"


def first_feasible(board, remaining, roster, picks_left):
    missing = []
    for slot in ROSTER_SLOTS:
        if slot == "BE":
            continue
        if not any(can_play_slot(player, slot) for player in roster):
            missing.append(slot)
    must_fill = picks_left <= len(missing)
    for identity in board:
        player = remaining.get(identity)
        if player is None:
            continue
        if not must_fill or any(can_play_slot(player, slot) for slot in missing):
            return player
    return next(iter(remaining.values()))


def draft_opponents(players, fixed_names, market):
    reserved = set(fixed_names)
    remaining = {_identity(player): deepcopy(player) for player in players if player["name"] not in reserved}
    rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
    by_name = {player["name"]: deepcopy(player) for player in players}
    rosters[HERO_SLOT] = [by_name[name] for name in fixed_names]
    board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1]) if identity in remaining]
    for overall in range(1, TEAM_COUNT * ROUNDS + 1):
        slot = _slot_at_pick(overall, TEAM_COUNT)
        if slot == HERO_SLOT:
            continue
        picks_left = ROUNDS - len(rosters[slot])
        selected = first_feasible(board, remaining, rosters[slot], picks_left)
        rosters[slot].append(selected)
        remaining.pop(_identity(selected), None)
    return rosters


def stress_rosters(rosters, run):
    stressed_rosters = {}
    for slot, roster in rosters.items():
        stressed_rosters[slot] = []
        for player in roster:
            identity = _identity(player)
            stats = dict(player.get("stats") or {})
            stressed = dict(stats)
            gp = float(stats.get("GP", 65) or 0)
            gp_rng = random.Random(f"fixed-2027:{run}:{identity}:GP")
            stressed["GP"] = max(0.0, min(82.0, gp * max(0.55, gp_rng.gauss(1.0, 0.12))))
            for key, value in stats.items():
                if key in {"GP", "FG%", "FT%", "3PT%", "A/TO"} or not isinstance(value, (int, float)):
                    continue
                stat_rng = random.Random(f"fixed-2027:{run}:{identity}:{key}")
                stressed[key] = max(0.0, float(value) * max(0.65, stat_rng.gauss(1.0, 0.08)))
            for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "3PA")):
                if made in stressed and attempted in stressed:
                    stressed[made] = min(stressed[made], stressed[attempted])
            stressed_rosters[slot].append({**player, "stats": stressed, "games_played": stressed["GP"]})
    return stressed_rosters


def summarize(outcomes):
    ranks = [row["league_rank"] for row in outcomes]
    matchup = [row["matchup_win_rate"] for row in outcomes]
    title_proxy = []
    for row in outcomes:
        p = row["matchup_win_rate"]
        if row["league_rank"] <= 2:
            title_proxy.append(p ** 2)
        elif row["league_rank"] <= 6:
            title_proxy.append(p ** 3)
        else:
            title_proxy.append(0.0)
    return {
        "average_league_rank": round(fmean(ranks), 3),
        "first_place_rate": round(sum(rank == 1 for rank in ranks) / len(ranks) * 100, 1),
        "top_two_rate": round(sum(rank <= 2 for rank in ranks) / len(ranks) * 100, 1),
        "top_four_rate": round(sum(rank <= 4 for rank in ranks) / len(ranks) * 100, 1),
        "playoff_top_six_rate": round(sum(rank <= 6 for rank in ranks) / len(ranks) * 100, 1),
        "matchup_win_rate": round(fmean(matchup) * 100, 1),
        "title_proxy_top6": round(fmean(title_proxy) * 100, 1),
        "average_category_score": round(fmean(row["average_matchup_score"] for row in outcomes), 3),
        "category_win_rates": {
            category: round(fmean(row["category_win_rate"][category] for row in outcomes) * 100, 1)
            for category in CATEGORIES
        },
        "category_ranks": {
            category: round(fmean(row["category_ranks"][category] for row in outcomes), 2)
            for category in CATEGORIES
        },
    }


def feasibility(players, target_names):
    by_name = {player["name"]: player for player in players}
    availability = Counter()
    completed = 0
    for run in range(FEASIBILITY_RUNS):
        market, _ = _scenario(players, 7_311_009, run)
        remaining = {_identity(player): player for player in players}
        rosters = {slot: [] for slot in range(1, TEAM_COUNT + 1)}
        board = [identity for identity, _ in sorted(market.items(), key=lambda row: row[1])]
        hit_all = True
        hero_round = 0
        for overall in range(1, TEAM_COUNT * ROUNDS + 1):
            slot = _slot_at_pick(overall, TEAM_COUNT)
            if slot == HERO_SLOT:
                target_name = target_names[hero_round]
                hero_round += 1
                target = by_name[target_name]
                target_identity = _identity(target)
                if target_identity in remaining:
                    selected = remaining[target_identity]
                    availability[target_name] += 1
                else:
                    hit_all = False
                    selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            else:
                selected = first_feasible(board, remaining, rosters[slot], ROUNDS - len(rosters[slot]))
            rosters[slot].append(selected)
            remaining.pop(_identity(selected), None)
        completed += int(hit_all)
    return {
        "runs": FEASIBILITY_RUNS,
        "exact_roster_rate": round(completed / FEASIBILITY_RUNS * 100, 2),
        "availability_by_pick": [
            {"pick": PICKS[index], "name": name, "rate": round(availability[name] / FEASIBILITY_RUNS * 100, 1)}
            for index, name in enumerate(target_names)
        ],
    }


def run():
    metadata = LeagueMetadata(LEAGUE_ID, SEASON, ESPN_S2, SWID)
    if not metadata.connect_to_league():
        raise ConnectionError("Could not connect to ESPN league")
    recs = get_draft_recommendations(metadata, TEAM_ID, "2027_projected", (), 300, (), None, False, True)
    players = prepare_benchmark_market(recs["players"], CATEGORIES, "espn_draft")
    # ESPN leaves some late players (including Tre Jones) unranked. Keep them in
    # the mock as end-game options instead of silently deleting them.
    for player in players:
        if player.get("espn_market_pick") is None:
            player["espn_market_pick"] = 220.0
    names = {player["name"] for player in players}
    required = set(CORE) | set(FIRST_PICKS)
    if missing := sorted(required - names):
        raise ValueError(f"Missing players: {missing}")

    variants = {name: [] for name in FIRST_PICKS}
    representative = None
    for index in range(RUNS):
        market, _ = _scenario(players, 9_721_005, index)
        for first in FIRST_PICKS:
            fixed = (first, *CORE)
            rosters = draft_opponents(players, fixed, market)
            stressed = stress_rosters(rosters, index)
            variants[first].append(evaluate_projected_rosters(stressed, HERO_SLOT, CATEGORIES))
            if first == "Jalen Johnson" and index == 0:
                scored = []
                for slot in range(1, TEAM_COUNT + 1):
                    evaluation = evaluate_projected_rosters(rosters, slot, CATEGORIES)
                    scored.append({
                        "slot": slot,
                        "rank": evaluation["league_rank"],
                        "category_score": round(evaluation["category_wins"], 2),
                        "roster": [player["name"] for player in rosters[slot]],
                    })
                representative = sorted(scored, key=lambda row: (row["rank"], -row["category_score"]))

    summaries = {name: summarize(rows) for name, rows in variants.items()}
    recommended = max(FIRST_PICKS, key=lambda name: (
        summaries[name]["title_proxy_top6"], summaries[name]["matchup_win_rate"]
    ))
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs_per_variant": RUNS,
        "team_count": TEAM_COUNT,
        "roster_size": ROUNDS,
        "draft_slot": HERO_SLOT,
        "picks": list(PICKS),
        "categories": list(CATEGORIES),
        "projection_source": recs.get("stats_source"),
        "market_source": recs.get("market_source"),
        "core": list(CORE),
        "variants": summaries,
        "recommended_first_pick": recommended,
        "feasibility": feasibility(players, (recommended, *CORE)),
        "representative_mock_for_jalen": representative,
        "method": {
            "power": "Exact fixed roster vs 13 stochastic ESPN-market opponent rosters; GP ±12%, per-game volume ±8%.",
            "title_proxy": "Top-6 playoffs; seeds 1-2 receive a bye; round win probability approximated by simulated matchup win rate.",
            "feasibility": "Live snake mock from slot 5; target selected only if still available at its planned pick.",
        },
        "limitations": [
            "Season-volume projections, not the exact weekly NBA schedule.",
            "Opponent managers follow noisy ESPN market order and positional feasibility; trades, waivers and streaming are excluded.",
            "Title probability is a playoff proxy, not a guarantee.",
        ],
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = run()
    print(json.dumps({
        "output": str(OUTPUT),
        "recommended": data["recommended_first_pick"],
        "variants": data["variants"],
        "feasibility": data["feasibility"],
    }, ensure_ascii=False, indent=2))
