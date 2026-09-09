"""Pure outer Monte Carlo for H2H-most-categories season standings."""

from __future__ import annotations

from collections import Counter, defaultdict
import random
from typing import Any, Iterable, Mapping


def simulate_season(
    teams: Iterable[Mapping[str, Any]],
    matchup_odds: Iterable[Mapping[str, Any]],
    playoff_team_count: int,
    *,
    trials: int = 400,
    seed: int = 0,
) -> list[dict[str, Any]]:
    teams = list(teams)
    trials = max(100, min(int(trials), 5000))
    rng = random.Random(seed)
    seed_counts = defaultdict(Counter)
    record_sums = defaultdict(lambda: [0.0, 0.0, 0.0])

    for _ in range(trials):
        records = {
            int(team["team_id"]): [float(team.get("wins", 0)), float(team.get("losses", 0)), float(team.get("ties", 0))]
            for team in teams
        }
        for matchup in matchup_odds:
            left, right = int(matchup["team1_id"]), int(matchup["team2_id"])
            draw = rng.random()
            if draw < matchup["p_win"]:
                records[left][0] += 1; records[right][1] += 1
            elif draw < matchup["p_win"] + matchup["p_tie"]:
                records[left][2] += 1; records[right][2] += 1
            else:
                records[left][1] += 1; records[right][0] += 1
        order = sorted(records, key=lambda team_id: (
            (records[team_id][0] + 0.5 * records[team_id][2]) / max(sum(records[team_id]), 1),
            records[team_id][0], rng.random(),
        ), reverse=True)
        for position, team_id in enumerate(order, 1):
            seed_counts[team_id][position] += 1
            for index in range(3):
                record_sums[team_id][index] += records[team_id][index]

    names = {int(team["team_id"]): team.get("team_name") or team.get("name") for team in teams}
    result = []
    for team_id in names:
        distribution = {str(seed): count / trials for seed, count in sorted(seed_counts[team_id].items())}
        expected_seed = sum(seed * probability for seed, probability in ((int(k), v) for k, v in distribution.items()))
        sums = record_sums[team_id]
        result.append({
            "team_id": team_id, "team_name": names[team_id],
            "p_playoff": sum(seed_counts[team_id][seed] for seed in range(1, playoff_team_count + 1)) / trials,
            "p_seed": distribution, "expected_seed": expected_seed,
            "expected_record": {"wins": sums[0] / trials, "losses": sums[1] / trials, "ties": sums[2] / trials},
        })
    return sorted(result, key=lambda row: (row["p_playoff"], -row["expected_seed"]), reverse=True)


def simulate_playoff_title(
    seeds: Iterable[Mapping[str, Any]],
    pair_probabilities: Mapping[tuple[int, int], float],
    *,
    trials: int = 1000,
    seed: int = 0,
) -> dict[int, float]:
    """Simulate a fixed standard seeded bracket, including first-round byes."""
    seeds = [row for row in seeds if row.get("seed") is not None]
    if not seeds:
        return {}
    by_seed = {int(row["seed"]): int(row["team_id"]) for row in seeds}
    size = 2
    while size < max(by_seed):
        size *= 2
    order = [1, 2]
    bracket_size = 2
    while bracket_size < size:
        bracket_size *= 2
        order = [value for placed in order for value in (placed, bracket_size + 1 - placed)]
    initial = [by_seed.get(seed_number) for seed_number in order]
    rng = random.Random(seed)
    champions = Counter()
    for _ in range(max(100, int(trials))):
        bracket = list(initial)
        while len(bracket) > 1:
            advanced = []
            for index in range(0, len(bracket), 2):
                left, right = bracket[index], bracket[index + 1]
                if left is None or right is None:
                    advanced.append(left if right is None else right)
                    continue
                probability = float(pair_probabilities.get((left, right), .5))
                advanced.append(left if rng.random() < probability else right)
            bracket = advanced
        if bracket[0] is not None:
            champions[bracket[0]] += 1
    total = sum(champions.values()) or 1
    return {team_id: champions[team_id] / total for team_id in by_seed.values()}
