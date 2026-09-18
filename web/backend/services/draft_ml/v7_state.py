"""Explicit market-free V7 state, strict roster legality and terminal targets."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np

from core.projection import can_play_slot
from ..draft_benchmark import _identity
from ..draft_evaluation import projected_team_totals, evaluate_projected_rosters
from ..draft_simulation import _slot_at_pick, snake_pick_numbers
from .evolution import rank_market_free_ensemble_candidates
from .simulation import _stress_rosters

CATEGORIES = ('FG%', 'FT%', '3PM', 'REB', 'AST', 'STL', 'BLK', 'PTS')
STATS = ('GP', 'FGM', 'FGA', 'FTM', 'FTA', '3PM', '3PA', 'REB', 'AST', 'STL', 'BLK', 'PTS')
SCALES = (82, 15, 30, 12, 15, 6, 15, 20, 15, 4, 5, 40)
POSITIONS = ('PG', 'SG', 'SF', 'PF', 'C', 'G', 'F', 'UT', 'BE')
PLAYER_DIM = len(CATEGORIES) + len(STATS) + len(POSITIONS)
GLOBAL_DIM = 3 + len(POSITIONS)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_teacher(genomes):
    """Merge identical deterministic scorers without changing ensemble voting."""
    groups = {}
    for genome in genomes:
        key = json.dumps(genome['weights'], sort_keys=True)
        if key not in groups:
            groups[key] = deepcopy(genome)
            groups[key]['ensemble_weight'] = 0.0
        groups[key]['ensemble_weight'] += float(genome.get('ensemble_weight', 1.0))
    return list(groups.values())


def compatible(player, slot):
    return slot in ('UT', 'UTIL', 'BE', 'BN', 'Bench') or can_play_slot(player, slot)


def assigned_count(roster, slots):
    """Maximum bipartite matching including every repeated ESPN roster slot."""
    occupied = {}
    def place(index, seen):
        for slot_index, slot in enumerate(slots):
            if slot_index in seen or not compatible(roster[index], slot):
                continue
            seen.add(slot_index)
            if slot_index not in occupied or place(occupied[slot_index], seen):
                occupied[slot_index] = index
                return True
        return False
    return sum(place(index, set()) for index in range(len(roster)))


def validate_snapshot(payload, team_count, rounds):
    if tuple(payload['categories']) != CATEGORIES:
        raise ValueError('V7 first experiment supports standard8 only')
    slots = payload['roster_slots']
    players = payload['players']
    if len(slots) != rounds or len(players) < team_count * rounds:
        raise ValueError('Roster size/player pool does not match experiment')
    if len({_identity(p) for p in players}) != len(players):
        raise ValueError('Duplicate player identities')
    for player in players:
        stats = player.get('stats', {})
        for key in STATS:
            if key not in stats or not isinstance(stats[key], (float, int)) or not math.isfinite(stats[key]) or stats[key] < 0:
                raise ValueError(f'Missing/invalid projected component {key}: {_identity(player)}')
        for made, attempted in (('FGM', 'FGA'), ('FTM', 'FTA'), ('3PM', '3PA')):
            if stats[made] > stats[attempted] + 1e-6:
                raise ValueError(f'Invalid shooting components: {_identity(player)}')
    return {'players': len(players), 'categories': list(CATEGORIES), 'slots': slots}


class State:
    def __init__(self, players, slots, team_count, rounds):
        self.players = players
        self.slots = tuple(slots)
        self.team_count = team_count
        self.rounds = rounds
        self.rosters = {s: [] for s in range(1, team_count + 1)}
        self.remaining = list(range(len(players)))
        self.pick = 1

    def clone(self):
        other = object.__new__(State)
        other.__dict__ = dict(self.__dict__)
        other.remaining = list(self.remaining)
        other.rosters = {s: list(rows) for s, rows in self.rosters.items()}
        return other

    @property
    def complete(self):
        return self.pick > self.team_count * self.rounds

    @property
    def slot(self):
        return _slot_at_pick(self.pick, self.team_count)

    def legal(self):
        roster = [self.players[i] for i in self.rosters[self.slot]]
        return [i for i in self.remaining if assigned_count([*roster, self.players[i]], self.slots) == len(roster) + 1]

    def apply(self, index):
        if index not in self.remaining:
            raise ValueError('Unavailable action')
        roster = self.rosters[self.slot]
        if assigned_count([self.players[i] for i in [*roster, index]], self.slots) != len(roster) + 1:
            raise ValueError('Illegal roster assignment')
        roster.append(index)
        self.remaining.remove(index)
        self.pick += 1

    def context(self):
        future = [p for p in snake_pick_numbers(self.slot, self.team_count, self.rounds) if p > self.pick]
        return SimpleNamespace(
            roster=[self.players[i] for i in self.rosters[self.slot]],
            remaining=[self.players[i] for i in self.remaining],
            opponent_rosters=[[self.players[i] for i in rows] for s, rows in self.rosters.items() if s != self.slot],
            categories=CATEGORIES, roster_slots=self.slots, eval_pick=self.pick,
            next_own_pick=future[0] if future else self.pick,
            rounds=self.rounds, team_count=self.team_count,
        )

    def teacher_scores(self, genomes, legal=None):
        legal = self.legal() if legal is None else legal
        if not legal:
            raise ValueError('No feasible action')
        by_id = {_identity(self.players[i]): i for i in legal}
        ranked = rank_market_free_ensemble_candidates([self.players[i] for i in legal], self.context(), genomes)
        return [(by_id[_identity(p)], score) for p, score in ranked]

    def encode(self, legal=None):
        # No player identity, order embedding, ADP or market rank enters the network.
        tokens = np.array([
            [float(p.get('z_scores', {}).get(c, 0)) / 4 for c in CATEGORIES]
            + [float(p['stats'][key]) / scale for key, scale in zip(STATS, SCALES)]
            + [float(compatible(p, position)) for position in POSITIONS]
            for p in self.players
        ], dtype=np.float32)
        roles = np.zeros(len(self.players), dtype=np.int64)
        for slot, roster in self.rosters.items():
            # Role 1 is us; 2..10 are opponents in cyclic draft-seat order.
            role = (slot - self.slot) % self.team_count + 1
            roles[roster] = role
        mask = np.zeros(len(self.players), dtype=np.bool_)
        mask[self.legal() if legal is None else legal] = True
        ctx = self.context()
        global_state = np.array([
            self.pick / (self.rounds * self.team_count),
            (ctx.next_own_pick - self.pick) / (2 * self.team_count),
            len(self.rosters[self.slot]) / self.rounds,
            *[sum(s == p for s in self.slots) / self.rounds for p in POSITIONS],
        ], dtype=np.float32)
        return tokens, roles, global_state, mask

    def targets(self, hero, seed, gp_noise, stat_noise):
        if not self.complete:
            raise ValueError('Terminal targets require a complete draft')
        rosters = {s: [self.players[i] for i in rows] for s, rows in self.rosters.items()}
        if any(len(rows) != self.rounds or assigned_count(rows, self.slots) != self.rounds for rows in rosters.values()):
            raise ValueError('Incomplete terminal roster')
        stressed = _stress_rosters(rosters, seed, gp_noise, stat_noise)
        totals = {s: projected_team_totals(rows, CATEGORIES) for s, rows in stressed.items()}
        probabilities = []
        for category in CATEGORIES:
            own = totals[hero][category]
            probabilities.append(sum(1 if own > t[category] + 1e-12 else 0.5 if abs(own - t[category]) <= 1e-12 else 0 for s, t in totals.items() if s != hero) / (self.team_count - 1))
        score = evaluate_projected_rosters(stressed, hero, CATEGORIES)
        return np.array([*probabilities, (score['league_rank'] - 1) / (self.team_count - 1), float(score['league_rank'] <= 4), float(score['league_rank'] == 1)], dtype=np.float32)
