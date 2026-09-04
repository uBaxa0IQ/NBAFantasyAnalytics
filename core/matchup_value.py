"""Opponent-relative utility. Scores are heuristics, not calibrated probabilities."""
import math
from .config import CATEGORIES, REVERSE_CATEGORIES
from .projection import project_team_stats


def combine_stats(*rows):
    players = [{'name': str(i), 'stats': row} for i, row in enumerate(rows)]
    return project_team_stats(players, {p['name']: 1 for p in players})


def matchup_utility(stats, opponent, punts=()):
    score = 0.0
    for cat in CATEGORIES:
        if cat in punts:
            continue
        left, right = stats.get(cat, 0), opponent.get(cat, 0)
        scale = max(abs(right) * .10, .015 if cat.endswith('%') else .1 if cat == 'A/TO' else 1.)
        margin = (left - right) * (-1 if cat in REVERSE_CATEGORIES else 1)
        score += .5 + .5 * math.tanh(margin / scale)
    return score


def add_matchup_values(players, baseline, opponent, punts=()):
    initial = matchup_utility(baseline, opponent, punts)
    return [{**player, 'lineup_value': matchup_utility(combine_stats(baseline, player['stats']), opponent, punts) - initial}
            for player in players]
