"""Keep the same manual selection policy on both sides of a trade."""

import math

from core.config import CATEGORIES


def selected_names_after_trade(selected, give, receive):
    return list(dict.fromkeys([name for name in selected if name not in give] + list(receive)))


def selected_roster_after_trade(selected, give, receive, roster_after, limit, punt_categories=()):
    """Carry a manual selection through a trade, then balance uneven exchanges."""
    roster_by_name = {player['name']: player for player in roster_after}
    selected = list(dict.fromkeys(name for name in selected if name in roster_by_name or name in give))
    selected_outgoing = set(selected) & set(give)
    names = [name for name in selected if name not in give and name in roster_by_name]
    if selected_outgoing:
        names.extend(name for name in receive if name in roster_by_name and name not in names)

    def total_z(name):
        scores = roster_by_name[name].get('z_scores') or {}
        return sum(
            value for category, value in scores.items()
            if category in CATEGORIES and category not in punt_categories
            if isinstance(value, (int, float)) and math.isfinite(value)
        )

    target_size = min(limit, len(selected), len(roster_by_name))
    while len(names) > limit:
        names.remove(min(names, key=total_z))
    if selected_outgoing and len(names) < target_size:
        candidates = (name for name in roster_by_name if name not in names)
        names.extend(sorted(candidates, key=total_z, reverse=True)[:target_size - len(names)])
    return names


def validate_ownership(ownership, moves):
    if len(moves) < 2:
        raise ValueError('Нужны две разные команды')
    for team_id, move in moves.items():
        if team_id not in ownership:
            raise ValueError('Команда не найдена')
        if len(move['give']) != len(set(move['give'])) or len(move['receive']) != len(set(move['receive'])):
            raise ValueError('Игрок указан несколько раз')
        if not set(move['give']).issubset(ownership[team_id]):
            raise ValueError('Отдаваемый игрок отсутствует в составе команды')
