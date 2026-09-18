"""League-conditioned draft state for variable categories, teams and roster slots."""
from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace

import numpy as np

from core.projection import can_play_slot
from core.z_score import calculate_z_scores_from_players
from ..draft_benchmark import _identity
from ..draft_evaluation import projected_team_totals
from ..draft_simulation import _slot_at_pick, snake_pick_numbers
from .simulation import _stress_rosters
from .evolution import rank_market_free_ensemble_candidates

CATEGORY_ALIASES = {'3P%': '3PT%'}
CATEGORY_VOCAB = ('FG%', 'FT%', '3PM', '3PT%', 'REB', 'AST', 'A/TO', 'STL', 'BLK', 'DD', 'PTS', 'TO')
CATEGORY_TO_ID = {name: index for index, name in enumerate(CATEGORY_VOCAB)}
RAW_STATS = ('GP', 'FGM', 'FGA', 'FTM', 'FTA', '3PM', '3PA', 'REB', 'AST', 'STL', 'BLK', 'PTS', 'TO', 'DD')
RAW_SCALES = (82, 15, 30, 12, 15, 6, 15, 20, 15, 4, 5, 40, 8, 1)
POSITIONS = ('PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UT', 'BE')
DRAFT_HISTORY_FEATURES = ('drafted_pick', 'draft_age')
RAW_DIM = len(RAW_STATS) + len(POSITIONS) + len(DRAFT_HISTORY_FEATURES)
GLOBAL_DIM = 5 + len(POSITIONS)


def normalize_categories(categories):
    result = tuple(CATEGORY_ALIASES.get(str(category).upper(), str(category).upper()) for category in categories)
    if not result or len(set(result)) != len(result):
        raise ValueError('Categories must be non-empty and unique')
    unknown = set(result) - set(CATEGORY_VOCAB)
    if unknown:
        raise ValueError(f'Unsupported universal categories: {sorted(unknown)}')
    return result


def normalize_slot(slot):
    value = str(slot).upper()
    return {'UTIL': 'UT', 'BN': 'BE', 'BENCH': 'BE'}.get(value, value)


def compatible(player, slot):
    slot = normalize_slot(slot)
    return slot in ('UT', 'BE') or can_play_slot(player, slot)


def assigned_count(roster, slots):
    occupied = {}
    normalized = tuple(normalize_slot(slot) for slot in slots)
    def place(index, seen):
        for slot_index, slot in enumerate(normalized):
            if slot_index in seen or not compatible(roster[index], slot):
                continue
            seen.add(slot_index)
            if slot_index not in occupied or place(occupied[slot_index], seen):
                occupied[slot_index] = index
                return True
        return False
    return sum(place(index, set()) for index in range(len(roster)))


def prepare_players(players, categories, reverse_categories=()):
    """Return independent player rows with utility-oriented Z scores for a format."""
    categories = normalize_categories(categories)
    reverse_categories = normalize_categories(reverse_categories) if reverse_categories else ()
    prepared = deepcopy(players)
    for index, player in enumerate(prepared):
        player.setdefault('name', str(player.get('id', index)))
        player.setdefault('position', ','.join(player.get('eligible_slots') or ()))
        player.setdefault('team_id', 0)
        player.setdefault('team_name', '')
    scored = calculate_z_scores_from_players(prepared, categories=list(categories), reverse_categories=set(reverse_categories))['players']
    if len(scored) != len(prepared):
        raise ValueError('Z-score preparation changed player count')
    for player, row in zip(prepared, scored):
        player['z_scores'] = row['z_scores']
    return prepared


class UniversalState:
    def __init__(self, players, slots, team_count, rounds=None, categories=None, reverse_categories=(), category_weights=None):
        self.players = players
        self.slots = tuple(normalize_slot(slot) for slot in slots)
        self.team_count = int(team_count)
        self.rounds = int(rounds if rounds is not None else len(self.slots))
        self.categories = normalize_categories(categories or CATEGORY_VOCAB[:8])
        self.reverse_categories = frozenset(normalize_categories(reverse_categories) if reverse_categories else ())
        unknown_reverse = self.reverse_categories - set(self.categories)
        if unknown_reverse:
            raise ValueError(f'Reverse category is not active: {sorted(unknown_reverse)}')
        weights = {CATEGORY_ALIASES.get(str(name).upper(), str(name).upper()): value
                   for name, value in (category_weights or {}).items()}
        self.category_weights = tuple(float(weights.get(category, 1.0)) for category in self.categories)
        if not 2 <= self.team_count <= 16 or self.rounds < 1 or len(self.slots) != self.rounds:
            raise ValueError('Invalid universal league dimensions')
        if len(players) < self.team_count * self.rounds:
            raise ValueError('Player pool is too small for the draft')
        self.rosters = {slot: [] for slot in range(1, self.team_count + 1)}
        self.remaining = list(range(len(players)))
        self.drafted_at = np.zeros(len(players), dtype=np.int32)
        self.pick = 1

    def clone(self):
        other = object.__new__(UniversalState)
        other.__dict__ = dict(self.__dict__)
        other.remaining = list(self.remaining)
        other.rosters = {slot: list(rows) for slot, rows in self.rosters.items()}
        other.drafted_at = self.drafted_at.copy()
        return other

    @property
    def complete(self):
        return self.pick > self.team_count * self.rounds

    @property
    def slot(self):
        return _slot_at_pick(self.pick, self.team_count)

    def legal(self):
        roster = [self.players[index] for index in self.rosters[self.slot]]
        return [index for index in self.remaining if assigned_count([*roster, self.players[index]], self.slots) == len(roster) + 1]

    def apply(self, index):
        if index not in self.remaining:
            raise ValueError('Unavailable action')
        roster = [self.players[i] for i in self.rosters[self.slot]]
        if assigned_count([*roster, self.players[index]], self.slots) != len(roster) + 1:
            raise ValueError('Illegal roster assignment')
        self.rosters[self.slot].append(index)
        self.remaining.remove(index)
        self.drafted_at[index] = self.pick
        self.pick += 1

    def context(self):
        future = [pick for pick in snake_pick_numbers(self.slot, self.team_count, self.rounds) if pick > self.pick]
        return SimpleNamespace(
            roster=[self.players[i] for i in self.rosters[self.slot]],
            remaining=[self.players[i] for i in self.remaining],
            opponent_rosters=[[self.players[i] for i in rows] for slot, rows in self.rosters.items() if slot != self.slot],
            categories=self.categories, reverse_categories=self.reverse_categories, roster_slots=self.slots,
            eval_pick=self.pick, next_own_pick=future[0] if future else self.pick,
            rounds=self.rounds, team_count=self.team_count,
        )

    def teacher_scores(self, genomes, legal=None):
        legal = self.legal() if legal is None else legal
        if not legal:
            raise ValueError('No feasible action')
        by_identity = {_identity(self.players[index]): index for index in legal}
        ranked = rank_market_free_ensemble_candidates([self.players[index] for index in legal], self.context(), genomes)
        return [(by_identity[_identity(player)], score) for player, score in ranked]

    def encode(self, legal=None):
        total_picks = self.team_count * self.rounds
        raw = np.asarray([
            [float(player.get('stats', {}).get(name, 0.0) or 0.0) / scale for name, scale in zip(RAW_STATS, RAW_SCALES)]
            + [float(compatible(player, position)) for position in POSITIONS]
            + [float(self.drafted_at[index]) / total_picks,
               float(max(0, self.pick - self.drafted_at[index])) / total_picks if self.drafted_at[index] else 0.0]
            for index, player in enumerate(self.players)
        ], dtype=np.float32)
        category_values = np.asarray([
            [float(player.get('z_scores', {}).get(category, 0.0) or 0.0) / 4.0 for category in self.categories]
            for player in self.players
        ], dtype=np.float32)
        category_ids = np.asarray([CATEGORY_TO_ID[category] for category in self.categories], dtype=np.int64)
        category_meta = np.asarray([
            [weight, float(category in self.reverse_categories)]
            for category, weight in zip(self.categories, self.category_weights)
        ], dtype=np.float32)
        category_mask = np.ones(len(self.categories), dtype=np.bool_)
        roles = np.zeros(len(self.players), dtype=np.int64)
        for owner, roster in self.rosters.items():
            role = (owner - self.slot) % self.team_count + 1
            roles[roster] = role
        mask = np.zeros(len(self.players), dtype=np.bool_)
        mask[self.legal() if legal is None else legal] = True
        ctx = self.context()
        global_state = np.asarray([
            self.pick / (self.rounds * self.team_count),
            (ctx.next_own_pick - self.pick) / (2 * self.team_count),
            len(self.rosters[self.slot]) / self.rounds,
            *[sum(slot == position for slot in self.slots) / self.rounds for position in POSITIONS],
            self.team_count / 16.0,
            self.rounds / 20.0,
        ], dtype=np.float32)
        return raw, category_values, category_ids, category_meta, category_mask, roles, global_state, mask

    def targets(self, hero, seed, gp_noise, stat_noise):
        if not self.complete:
            raise ValueError('Terminal targets require a complete draft')
        rosters = {slot: [self.players[i] for i in rows] for slot, rows in self.rosters.items()}
        if any(len(rows) != self.rounds or assigned_count(rows, self.slots) != self.rounds for rows in rosters.values()):
            raise ValueError('Incomplete terminal roster')
        stressed = _stress_rosters(rosters, seed, gp_noise, stat_noise)
        totals = {slot: projected_team_totals(rows, self.categories) for slot, rows in stressed.items()}
        category_results = []
        for category in self.categories:
            own = totals[hero][category]
            if category in self.reverse_categories:
                own = -own
            wins = 0.0
            for slot, values in totals.items():
                if slot == hero: continue
                other = -values[category] if category in self.reverse_categories else values[category]
                wins += 1.0 if own > other + 1e-12 else .5 if abs(own - other) <= 1e-12 else 0.0
            category_results.append(wins / (self.team_count - 1))
        scores = {}
        for slot in totals:
            score = 0.0
            for category in self.categories:
                own = totals[slot][category]
                direction = -1.0 if category in self.reverse_categories else 1.0
                score += sum(1.0 if direction * own > direction * values[category] + 1e-12 else
                             .5 if abs(own - values[category]) <= 1e-12 else 0.0
                             for other, values in totals.items() if other != slot) / (self.team_count - 1)
            scores[slot] = score
        rank = 1 + sum(value > scores[hero] + 1e-12 for slot, value in scores.items() if slot != hero)
        return np.asarray([*category_results, (rank - 1) / (self.team_count - 1),
            float(rank <= min(4, self.team_count)), float(rank == 1)], dtype=np.float32)
