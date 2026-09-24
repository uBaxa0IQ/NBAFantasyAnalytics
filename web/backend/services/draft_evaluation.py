"""Independent roster evaluation based on projected season volume."""

from __future__ import annotations

from collections import defaultdict
import math

from core.config import CATEGORIES, REVERSE_CATEGORIES


def projected_team_totals(roster, categories=None):
    categories = list(categories or CATEGORIES)
    component_totals = defaultdict(float)
    z_fallback = defaultdict(float)
    has_raw = defaultdict(bool)
    for player in roster:
        stats = player.get("stats") or {}
        raw_gp = stats.get("GP")
        gp = float(raw_gp) if isinstance(raw_gp, (int, float)) else 82.0
        gp = max(0.0, gp)
        for key, value in stats.items():
            if key == "GP" or not isinstance(value, (int, float)):
                continue
            component_totals[key] += float(value) * gp
            has_raw[key] = True
        for category, value in (player.get("z_scores") or {}).items():
            if isinstance(value, (int, float)):
                z_fallback[category] += float(value)

    totals = {}
    for category in categories:
        if category == "FG%" and component_totals["FGA"]:
            totals[category] = component_totals["FGM"] / component_totals["FGA"]
        elif category == "FT%" and component_totals["FTA"]:
            totals[category] = component_totals["FTM"] / component_totals["FTA"]
        elif category == "3PT%" and component_totals["3PA"]:
            totals[category] = component_totals["3PM"] / component_totals["3PA"]
        elif category == "A/TO" and component_totals["TO"]:
            totals[category] = component_totals["AST"] / component_totals["TO"]
        elif has_raw[category]:
            totals[category] = component_totals[category]
        else:
            totals[category] = z_fallback[category]
    return totals


def evaluate_projected_rosters(team_rosters, own_slot, categories=None):
    """Score projected roster volume under every supplied league category."""
    categories = list(categories or CATEGORIES)
    totals = {slot: projected_team_totals(roster, categories) for slot, roster in team_rosters.items()}
    scores = {slot: 0.0 for slot in totals}
    own_matchup_scores = []
    own_category_points = defaultdict(float)
    category_ranks = {}
    for category in categories:
        reverse = category in REVERSE_CATEGORIES
        ordered = sorted(totals, key=lambda slot: totals[slot][category], reverse=not reverse)
        category_ranks[category] = ordered.index(own_slot) + 1
    slots = list(totals)
    for left_index, left in enumerate(slots):
        for right in slots[left_index + 1:]:
            left_matchup_score = 0.0
            right_matchup_score = 0.0
            for category in categories:
                left_value = totals[left][category]
                right_value = totals[right][category]
                if category in REVERSE_CATEGORIES:
                    left_value, right_value = -left_value, -right_value
                if left_value > right_value + 1e-12:
                    scores[left] += 1
                    left_matchup_score += 1
                elif right_value > left_value + 1e-12:
                    scores[right] += 1
                    right_matchup_score += 1
                else:
                    scores[left] += 0.5
                    scores[right] += 0.5
                    left_matchup_score += 0.5
                    right_matchup_score += 0.5
            if left == own_slot:
                own_matchup_scores.append(left_matchup_score)
            elif right == own_slot:
                own_matchup_scores.append(right_matchup_score)
    opponent_count = max(1, len(slots) - 1)
    scores = {slot: value / opponent_count for slot, value in scores.items()}
    own_score = scores[own_slot]
    rank = 1 + sum(value > own_score + 1e-12 for slot, value in scores.items() if slot != own_slot)
    opponent_totals = [values for slot, values in totals.items() if slot != own_slot]
    opponent_average = {
        category: sum(values[category] for values in opponent_totals) / max(1, len(opponent_totals))
        for category in categories
    }
    for category in categories:
        own_value = totals[own_slot][category]
        reverse = category in REVERSE_CATEGORIES
        for values in opponent_totals:
            left_value, right_value = own_value, values[category]
            if reverse:
                left_value, right_value = -left_value, -right_value
            own_category_points[category] += (
                1.0 if left_value > right_value + 1e-12
                else 0.5 if abs(left_value - right_value) <= 1e-12
                else 0.0
            )
    category_win_rate = {
        category: own_category_points[category] / opponent_count
        for category in categories
    }
    category_margin_z = {}
    for category in categories:
        values = [row[category] for row in opponent_totals]
        mean = sum(values) / max(1, len(values))
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
        scale = math.sqrt(variance)
        direction = -1.0 if category in REVERSE_CATEGORIES else 1.0
        category_margin_z[category] = direction * (totals[own_slot][category] - mean) / max(scale, 1e-12)
    midpoint = len(categories) / 2.0
    minimum_win = len(categories) // 2 + 1
    matchup_wins = sum(score > midpoint + 1e-12 for score in own_matchup_scores)
    matchup_ties = sum(abs(score - midpoint) <= 1e-12 for score in own_matchup_scores)
    matchup_losses = opponent_count - matchup_wins - matchup_ties
    decisive_wins = sum(score >= minimum_win + 1 - 1e-12 for score in own_matchup_scores)
    narrow_wins = sum(minimum_win - 1e-12 <= score < minimum_win + 1 - 1e-12 for score in own_matchup_scores)
    return {
        "category_wins": own_score,
        "league_rank": rank,
        "matchup_wins": matchup_wins,
        "matchup_ties": matchup_ties,
        "matchup_losses": matchup_losses,
        "category_ranks": category_ranks,
        "category_totals": totals[own_slot],
        "category_margin": {
            category: totals[own_slot][category] - opponent_average[category]
            for category in categories
        },
        "category_win_rate": category_win_rate,
        "category_margin_z": category_margin_z,
        "matchup_win_rate": matchup_wins / opponent_count,
        "matchup_tie_rate": matchup_ties / opponent_count,
        "matchup_loss_rate": matchup_losses / opponent_count,
        "decisive_matchup_win_rate": decisive_wins / opponent_count,
        "narrow_matchup_win_rate": narrow_wins / opponent_count,
        "average_matchup_score": sum(own_matchup_scores) / opponent_count,
        "average_matchup_margin": sum(score - midpoint for score in own_matchup_scores) / opponent_count,
        "minimum_matchup_score": min(own_matchup_scores, default=midpoint),
    }
