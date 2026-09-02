"""Проекция фэнтези-состава по NBA-календарю и доступным lineup slots."""

from functools import lru_cache
from typing import Any, Dict, Iterable, List, Sequence, Tuple


DEFAULT_LINEUP_SLOTS: Tuple[str, ...] = (
    "PG",
    "SG",
    "SF",
    "PF",
    "C",
    "G",
    "F",
    "UT",
    "UT",
    "UT",
)

COUNTING_STATS = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD")
COMPONENT_STATS = ("FGM", "FGA", "FTM", "FTA", "3PA", "TO")


def can_play_slot(player: Dict[str, Any], slot: str) -> bool:
    if slot == "UT":
        return True

    eligible = set(player.get("eligible_slots") or player.get("eligibleSlots") or [])
    position = player.get("position") or ""
    if slot in eligible or slot == position:
        return True
    if slot == "G":
        return bool(eligible.intersection({"PG", "SG", "G"})) or position in {"PG", "SG"}
    if slot == "F":
        return bool(eligible.intersection({"SF", "PF", "F"})) or position in {"SF", "PF"}
    return False


def player_value(player: Dict[str, Any], punt_categories: Iterable[str] = ()) -> float:
    punt = set(punt_categories)
    return sum(
        float(value)
        for category, value in (player.get("z_scores") or {}).items()
        if category not in punt and isinstance(value, (int, float))
    )


def has_game(player: Dict[str, Any], scoring_period: int) -> bool:
    schedule = player.get("schedule") or {}
    return str(scoring_period) in schedule or scoring_period in schedule


def optimize_daily_lineup(
    players: Sequence[Dict[str, Any]],
    slots: Sequence[str] = DEFAULT_LINEUP_SLOTS,
    punt_categories: Iterable[str] = (),
) -> Dict[str, Any]:
    """Максимизирует суммарную ценность lineup через DP по битовой маске слотов."""
    candidates = [player for player in players if player.get("available", True)]
    values = [player_value(player, punt_categories) for player in candidates]

    @lru_cache(maxsize=None)
    def solve(player_index: int, used_mask: int):
        if player_index >= len(candidates):
            return 0, 0.0, ()

        best_count, best_value, best_assignments = solve(player_index + 1, used_mask)
        player = candidates[player_index]
        for slot_index, slot in enumerate(slots):
            slot_bit = 1 << slot_index
            if used_mask & slot_bit or not can_play_slot(player, slot):
                continue
            remaining_count, remaining_value, remaining_assignments = solve(
                player_index + 1,
                used_mask | slot_bit,
            )
            candidate_count = remaining_count + 1
            candidate_value = values[player_index] + remaining_value
            if (candidate_count, candidate_value) > (best_count, best_value):
                best_count = candidate_count
                best_value = candidate_value
                best_assignments = ((player_index, slot_index),) + remaining_assignments
        return best_count, best_value, best_assignments

    _, total_value, assignments = solve(0, 0)
    starters = []
    selected_indexes = set()
    for player_index, slot_index in assignments:
        selected_indexes.add(player_index)
        starters.append(
            {
                "slot": slots[slot_index],
                "slot_index": slot_index,
                "player": candidates[player_index],
                "value": values[player_index],
            }
        )
    starters.sort(key=lambda item: item["slot_index"])

    return {
        "starters": starters,
        "bench": [player for index, player in enumerate(candidates) if index not in selected_indexes],
        "total_value": total_value,
    }


def build_matchup_lineups(
    players: Sequence[Dict[str, Any]],
    scoring_periods: Sequence[int],
    slots: Sequence[str] = DEFAULT_LINEUP_SLOTS,
    punt_categories: Iterable[str] = (),
) -> Dict[str, Any]:
    days = []
    selected_games: Dict[str, int] = {player["name"]: 0 for player in players}

    for scoring_period in scoring_periods:
        playing = [player for player in players if has_game(player, scoring_period)]
        optimized = optimize_daily_lineup(playing, slots, punt_categories)
        for starter in optimized["starters"]:
            name = starter["player"]["name"]
            selected_games[name] = selected_games.get(name, 0) + 1
        days.append(
            {
                "scoring_period": scoring_period,
                "starters": optimized["starters"],
                "bench": optimized["bench"],
                "total_value": optimized["total_value"],
            }
        )

    return {"days": days, "selected_games": selected_games}


def project_team_stats(
    players: Sequence[Dict[str, Any]],
    selected_games: Dict[str, int],
) -> Dict[str, float]:
    """Агрегирует per-game stats по выбранным player-games."""
    totals = {stat: 0.0 for stat in (*COUNTING_STATS, *COMPONENT_STATS)}

    for player in players:
        games = selected_games.get(player["name"], 0)
        stats = player.get("stats") or {}
        if games <= 0:
            continue
        for stat in totals:
            value = stats.get(stat, 0.0)
            if isinstance(value, (int, float)):
                totals[stat] += float(value) * games

    totals["FG%"] = totals["FGM"] / totals["FGA"] if totals["FGA"] else 0.0
    totals["FT%"] = totals["FTM"] / totals["FTA"] if totals["FTA"] else 0.0
    totals["3PT%"] = totals["3PM"] / totals["3PA"] if totals["3PA"] else 0.0
    totals["A/TO"] = totals["AST"] / totals["TO"] if totals["TO"] else totals["AST"]
    return totals


def get_matchup_scoring_periods(league, matchup_period: int) -> List[int]:
    periods = getattr(league, "matchup_ids", {}).get(int(matchup_period), [])
    return sorted(int(period) for period in periods)


def get_remaining_scoring_periods(league, matchup_period: int) -> List[int]:
    current_scoring_period = int(getattr(league, "current_week", 0) or 0)
    return [
        period
        for period in get_matchup_scoring_periods(league, matchup_period)
        if period >= current_scoring_period
    ]
