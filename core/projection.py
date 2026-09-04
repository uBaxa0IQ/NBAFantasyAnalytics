"""Проекция фэнтези-состава по NBA-календарю и доступным lineup slots."""

from typing import Any, Dict, Iterable, List, Sequence, Tuple
from datetime import datetime, date


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
    if '/' in slot:
        return any(can_play_slot(player, part) for part in slot.split('/'))
    if slot in eligible or slot == position:
        return True
    if slot == "G":
        return bool(eligible.intersection({"PG", "SG", "G"})) or position in {"PG", "SG"}
    if slot == "F":
        return bool(eligible.intersection({"SF", "PF", "F"})) or position in {"SF", "PF"}
    return False


def player_value(player: Dict[str, Any], punt_categories: Iterable[str] = ()) -> float:
    if "lineup_value" in player:
        return float(player["lineup_value"])
    punt = set(punt_categories)
    return sum(
        float(value)
        for category, value in (player.get("z_scores") or {}).items()
        if category not in punt and isinstance(value, (int, float))
    )


def has_game(player: Dict[str, Any], scoring_period: int) -> bool:
    schedule = player.get("schedule") or {}
    if player.get('future_only'):
        game = schedule.get(str(scoring_period), schedule.get(scoring_period)) or {}
        date = game.get('date')
        if isinstance(date, datetime) and date <= datetime.now(date.tzinfo):
            return False
    return str(scoring_period) in schedule or scoring_period in schedule


def optimize_daily_lineup(
    players: Sequence[Dict[str, Any]],
    slots: Sequence[str] = DEFAULT_LINEUP_SLOTS,
    punt_categories: Iterable[str] = (),
    fill_slots: bool = True,
) -> Dict[str, Any]:
    """Maximum-weight assignment with optional empty slots (Hungarian algorithm)."""
    candidates = [player for player in players if player.get("available", True)]
    values = [player_value(player, punt_categories) for player in candidates]

    bonus = 2 * sum(abs(value) for value in values) + 1 if fill_slots else 0
    forbidden = sum(abs(value) for value in values) + bonus * len(slots) + 1
    costs = [[-(values[i] + bonus) if can_play_slot(player, slot) else forbidden
              for i, player in enumerate(candidates)] + [0.0] * len(slots) for slot in slots]
    rows, columns = len(slots), len(candidates) + len(slots)
    u, v = [0.0] * (rows + 1), [0.0] * (columns + 1)
    matched, previous = [0] * (columns + 1), [0] * (columns + 1)
    for row in range(1, rows + 1):
        matched[0], column = row, 0
        minimum, used = [float('inf')] * (columns + 1), [False] * (columns + 1)
        while True:
            used[column] = True
            active_row, delta, next_column = matched[column], float('inf'), 0
            for j in range(1, columns + 1):
                if not used[j]:
                    cost = costs[active_row - 1][j - 1] - u[active_row] - v[j]
                    if cost < minimum[j]:
                        minimum[j], previous[j] = cost, column
                    if minimum[j] < delta:
                        delta, next_column = minimum[j], j
            for j in range(columns + 1):
                if used[j]:
                    u[matched[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            column = next_column
            if matched[column] == 0:
                break
        while column:
            prior = previous[column]
            matched[column] = matched[prior]
            column = prior
    assignments = [(j - 1, matched[j] - 1) for j in range(1, len(candidates) + 1) if matched[j]]
    total_value = sum(values[i] for i, _ in assignments)
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
    fill_slots: bool = True,
) -> Dict[str, Any]:
    days = []
    selected_games: Dict[str, int] = {player["name"]: 0 for player in players}

    day_cache = {}
    for scoring_period in scoring_periods:
        playing = []
        for player in players:
            if not has_game(player, scoring_period):
                continue
            return_date = player.get('expected_return_date')
            game_date = (player.get('schedule', {}).get(str(scoring_period), player.get('schedule', {}).get(scoring_period)) or {}).get('date')
            if isinstance(return_date, str):
                try:
                    return_date = date.fromisoformat(return_date[:10])
                except ValueError:
                    return_date = None
            if isinstance(return_date, datetime):
                return_date = return_date.date()
            if isinstance(return_date, date) and isinstance(game_date, datetime) and game_date.date() >= return_date and player.get('lineup_slot') != 'IR':
                player = {**player, 'available': True}
            playing.append(player)
        key = tuple(id(player) for player in playing)
        if key not in day_cache:
            day_cache[key] = optimize_daily_lineup(playing, slots, punt_categories, fill_slots)
        optimized = day_cache[key]
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
