"""Offline roster constructor: category targets and snake-assembly odds."""

from __future__ import annotations

from copy import deepcopy

from core.config import CATEGORIES

from .draft_benchmark import _identity, _scenario
from .draft_evaluation import projected_team_totals
from .draft_mock import _public_player
from .draft_simulation import _market_position, snake_pick_numbers


WORKING_CATEGORIES = ("FG%", "REB", "AST", "A/TO", "STL", "BLK", "DD")
CORE_REACH = 8
AVAILABILITY_RUNS = 200
AVAILABILITY_SEED = 7741

# Season totals from 240 14-team mocks. Percents are 0-1 ratios.
CATEGORY_TARGETS = {
    "FG%": {"top3": 0.504, "first": 0.524, "goal": 0.515, "goal_high": 0.515},
    "REB": {"top3": 5734.0, "first": 6190.0, "goal": 6000.0, "goal_high": 6000.0},
    "AST": {"top3": 3904.0, "first": 4293.0, "goal": 4100.0, "goal_high": 4100.0},
    "A/TO": {"top3": 2.16, "first": 2.41, "goal": 2.30, "goal_high": 2.30},
    "STL": {"top3": 994.0, "first": 1059.0, "goal": 1030.0, "goal_high": 1030.0},
    "BLK": {"top3": 718.0, "first": 828.0, "goal": 800.0, "goal_high": 800.0},
    "DD": {"top3": 173.0, "first": 208.0, "goal": 200.0, "goal_high": 200.0},
}


def _player_id(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize_roster_ids(player_ids, rounds):
    rounds = max(1, int(rounds or 1))
    ids = list(player_ids or ())[:rounds]
    while len(ids) < rounds:
        ids.append(None)
    seen = set()
    normalized = []
    for value in ids:
        player_id = _player_id(value)
        if player_id is None or player_id in seen:
            normalized.append(None)
            continue
        seen.add(player_id)
        normalized.append(player_id)
    return normalized


def _band(value, target):
    if value is None or target is None:
        return "empty"
    if value + 1e-12 >= target["first"]:
        return "first"
    if value + 1e-12 >= target["goal"]:
        return "goal"
    if value + 1e-12 >= target["top3"]:
        return "top3"
    return "below"


def _category_row(category, value, punt=False, incomplete=False):
    target = CATEGORY_TARGETS.get(category)
    band = "punt" if punt else _band(value, target)
    if incomplete and not punt and band == "below":
        band = "building"
    return {
        "category": category,
        "value": None if value is None else round(float(value), 4),
        "top3": None if target is None else target["top3"],
        "first": None if target is None else target["first"],
        "goal": None if target is None else target["goal"],
        "goal_high": None if target is None else target["goal_high"],
        "band": band,
        "working": category in WORKING_CATEGORIES and not punt,
    }


def _is_core(player, pick):
    market = _market_position(player)
    if market is None or pick is None:
        return True
    return float(market) <= float(pick) + CORE_REACH


def simulate_assembly(players, roster_ids, slot, team_count, rounds, runs=AVAILABILITY_RUNS):
    """Share of noisy-market snakes where each assigned name is still there at its pick."""
    by_id = {
        int(player["player_id"]): player
        for player in players
        if player.get("player_id") is not None
    }
    picks = snake_pick_numbers(slot, team_count, rounds)
    planned = []
    for index, player_id in enumerate(roster_ids):
        player = by_id.get(player_id) if player_id is not None else None
        pick = picks[index] if index < len(picks) else None
        planned.append((index, pick, player_id, player))

    empty = {
        "runs": 0,
        "full_rate": None,
        "core_rate": None,
        "slots": [
            {
                "index": index,
                "pick": pick,
                "player_id": player_id,
                "available": None,
                "core": False,
            }
            for index, pick, player_id, _player in planned
        ],
    }
    named = [(index, pick, player) for index, pick, _player_id, player in planned if player is not None]
    if not named:
        return empty

    identities = [_identity(player) for player in players]
    total_picks = team_count * rounds
    target_at = {pick: (index, player) for index, pick, player in named if pick}
    slot_hits = {index: 0 for index, _pick, _player in named}
    core_indexes = {
        index for index, pick, player in named if _is_core(player, pick)
    }
    named_indexes = {index for index, _pick, _player in named}
    full_hits = 0
    core_hits = 0

    def take_next(order, taken, cursor):
        while cursor < len(order) and order[cursor] in taken:
            cursor += 1
        if cursor < len(order):
            taken.add(order[cursor])
            cursor += 1
        return cursor

    for run in range(max(1, int(runs))):
        market, _opponent = _scenario(players, AVAILABILITY_SEED, run)
        order = sorted(identities, key=lambda identity: market.get(identity, 10_000))
        taken = set()
        cursor = 0
        run_hits = set()
        for overall in range(1, total_picks + 1):
            target = target_at.get(overall)
            if target is not None:
                index, player = target
                identity = _identity(player)
                if identity not in taken:
                    taken.add(identity)
                    run_hits.add(index)
                    slot_hits[index] += 1
                else:
                    cursor = take_next(order, taken, cursor)
                continue
            cursor = take_next(order, taken, cursor)
        if named_indexes <= run_hits:
            full_hits += 1
        if not core_indexes or core_indexes <= run_hits:
            core_hits += 1

    run_count = max(1, int(runs))
    return {
        "runs": run_count,
        "full_rate": round(100.0 * full_hits / run_count, 1),
        "core_rate": round(100.0 * core_hits / run_count, 1),
        "slots": [
            {
                "index": index,
                "pick": pick,
                "player_id": player_id,
                "available": None if player is None else round(100.0 * slot_hits.get(index, 0) / run_count, 1),
                "core": bool(player is not None and _is_core(player, pick)),
            }
            for index, pick, player_id, player in planned
        ],
        "planned": len(named),
        "core_count": len(core_indexes),
    }


def evaluate_constructor_roster(
    players,
    player_ids,
    slot,
    team_count,
    rounds,
    categories=None,
    punt_categories=(),
    runs=AVAILABILITY_RUNS,
):
    categories = list(categories or CATEGORIES)
    punts = set(punt_categories or ())
    roster_ids = normalize_roster_ids(player_ids, rounds)
    by_id = {
        int(player["player_id"]): player
        for player in players
        if player.get("player_id") is not None
    }
    roster = [deepcopy(by_id[player_id]) for player_id in roster_ids if player_id in by_id]
    totals = projected_team_totals(roster, categories) if roster else {category: None for category in categories}
    working = [category for category in WORKING_CATEGORIES if category in categories]
    in_goal = [
        category for category in working
        if category not in punts and _band(totals.get(category), CATEGORY_TARGETS.get(category)) in {"goal", "first"}
    ]
    incomplete = len(roster) < int(rounds)
    return {
        "roster_ids": roster_ids,
        "filled": len(roster),
        "rounds": int(rounds),
        "totals": {
            category: None if totals.get(category) is None else round(float(totals[category]), 4)
            for category in categories
        },
        "categories": [
            _category_row(
                category,
                totals.get(category),
                punt=category in punts,
                incomplete=incomplete,
            )
            for category in categories
        ],
        "working_in_goal": len(in_goal),
        "working_count": len([category for category in working if category not in punts]),
        "assembly": simulate_assembly(players, roster_ids, slot, team_count, rounds, runs=runs),
        "picks": snake_pick_numbers(slot, team_count, rounds),
    }


def constructor_board(board, punt_categories=()):
    players = [_public_player(player, punt_categories) for player in board["players"]]
    slot = int(board["slot"])
    team_count = int(board["team_count"])
    rounds = int(board["rounds"])
    return {
        "players": players,
        "slot": slot,
        "team_count": team_count,
        "rounds": rounds,
        "picks": snake_pick_numbers(slot, team_count, rounds),
        "order_known": bool(board.get("order_known", True)),
        "categories": list(board.get("categories") or CATEGORIES),
        "working_categories": list(WORKING_CATEGORIES),
        "targets": CATEGORY_TARGETS,
    }
