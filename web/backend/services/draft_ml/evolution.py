"""Market-free population self-play for robust 8-category draft policies."""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
from statistics import fmean, pstdev

from core.projection import can_play_slot

from ..draft_benchmark import _feasible_pool, _identity
from ..draft_evaluation import evaluate_projected_rosters
from ..draft_simulation import _next_turn_pick, _slot_at_pick, snake_pick_numbers, unfilled_roster_slots
from ..draft_strategy import strategy_probabilities
from .simulation import _stress_rosters


POLICY_TYPE = "market_free_linear_v1"


@dataclass(frozen=True)
class EvolutionConfig:
    population_size: int = 16
    generations: int = 24
    drafts_per_generation: int = 32
    final_drafts: int = 96
    team_count: int = 10
    rounds: int = 13
    elite_count: int = 4
    parent_pool: int = 8
    hall_slots_per_draft: int = 3
    hall_max_size: int = 32
    anchor_slots_per_draft: int = 0
    anchor_pool_size: int = 24
    validation_drafts: int = 0
    finalist_count: int = 8
    mutation_sigma: float = 0.16
    mutation_probability: float = 0.28
    cvar_fraction: float = 0.20
    downside_weight: float = 0.40
    league_rank_weight: float = 0.08
    top_four_weight: float = 0.0
    top_one_weight: float = 0.0
    niche_elite_count: int = 0
    projection_gp_stddev: float = 0.12
    projection_stat_stddev: float = 0.08
    workers: int = 8
    seed: int = 2_609_601
    candidate_limit: int = 300
    early_stopping_patience: int = 0
    early_stopping_min_delta: float = 0.0
    early_stopping_min_generations: int = 0

    def validate(self):
        if self.population_size < 4 or self.team_count < 2:
            raise ValueError("population/team_count too small")
        if self.generations < 1 or self.drafts_per_generation < 1 or self.final_drafts < 1 or self.rounds < 1:
            raise ValueError("generations, drafts and rounds must be positive")
        if not 1 <= self.elite_count <= self.parent_pool <= self.population_size:
            raise ValueError("invalid elite/parent selection")
        if self.elite_count + self.niche_elite_count > self.parent_pool:
            raise ValueError("performance and niche elites exceed parent pool")
        if self.top_four_weight < 0 or self.top_one_weight < 0 or self.niche_elite_count < 0:
            raise ValueError("invalid multi-objective selection configuration")
        if not 0 <= self.hall_slots_per_draft < self.team_count:
            raise ValueError("invalid hall slots")
        if not 0 <= self.anchor_slots_per_draft < self.team_count:
            raise ValueError("invalid anchor slots")
        if self.hall_slots_per_draft + self.anchor_slots_per_draft >= self.team_count:
            raise ValueError("hall and anchor slots leave no current-policy seat")
        if self.anchor_pool_size < self.anchor_slots_per_draft:
            raise ValueError("anchor pool is smaller than anchor slots")
        if self.validation_drafts < 0 or self.finalist_count < 1:
            raise ValueError("invalid validation/finalist configuration")
        if not 0 < self.cvar_fraction <= 1:
            raise ValueError("invalid CVaR fraction")
        if self.workers < 1 or self.candidate_limit < 2:
            raise ValueError("invalid workers/candidate limit")
        if self.early_stopping_patience < 0 or self.early_stopping_min_generations < 0:
            raise ValueError("invalid early stopping configuration")
        if self.early_stopping_min_delta < 0:
            raise ValueError("early_stopping_min_delta must be non-negative")
        return self


def feature_names(categories):
    names = [
        "general_z", "gp", "position_fit", "late_position_fit",
        "multi_position", "balance_after", "floor_after", "active_total",
    ]
    for category in categories:
        names.extend((
            f"z::{category}", f"active_z::{category}", f"need::{category}",
            f"build::{category}", f"opponent_denial::{category}",
            f"replacement_gap::{category}", f"urgency::{category}",
        ))
    return tuple(names)


def _number(value, default=0.0):
    return float(value) if isinstance(value, (int, float)) else float(default)


def _category_strength(roster, category):
    return sum(_number((player.get("z_scores") or {}).get(category)) for player in roster)


def market_free_feature_rows(
    candidates, *, roster, remaining, opponent_rosters, categories, roster_slots,
    overall_pick, next_own_pick, rounds, team_count,
):
    """Return state-normalized action features with no market/rank inputs."""
    candidates = list(candidates)
    categories = tuple(categories)
    roster = list(roster or ())
    remaining = list(remaining or ())
    opponents = [list(rows) for rows in opponent_rosters or ()]
    names = feature_names(categories)
    strategy_rows = strategy_probabilities(roster, categories, rounds)
    active = {
        category: sum(
            _number(row.get("probability"))
            for row in strategy_rows
            if category not in tuple(row.get("punt_categories") or ())
        )
        for category in categories
    }
    own = {category: _category_strength(roster, category) for category in categories}
    opponent = {
        category: fmean([_category_strength(rows, category) for rows in opponents]) if opponents else 0.0
        for category in categories
    }
    picks_to_next = max(1, int((next_own_pick or overall_pick) - overall_pick))
    replacement = {}
    for category in categories:
        ordered = sorted(
            (_number((player.get("z_scores") or {}).get(category)) for player in remaining),
            reverse=True,
        )
        replacement[category] = ordered[min(len(ordered) - 1, picks_to_next)] if ordered else 0.0
    missing = tuple(unfilled_roster_slots(roster, roster_slots))
    future_picks = [
        pick for pick in snake_pick_numbers(
            _slot_at_pick(overall_pick, team_count), team_count, rounds,
        ) if pick >= overall_pick
    ]
    late = bool(missing and len(future_picks) <= len(missing))
    raw = []
    for candidate in candidates:
        z_scores = candidate.get("z_scores") or {}
        strengths_after = [own[category] + _number(z_scores.get(category)) for category in categories]
        row = {
            "general_z": _number(candidate.get("general_z", candidate.get("total_z", 0))),
            "gp": _number((candidate.get("stats") or {}).get("GP", candidate.get("games_played", 0))) / 82.0,
            "position_fit": float(any(can_play_slot(candidate, slot) for slot in missing)) if missing else 1.0,
            "late_position_fit": float(late and any(can_play_slot(candidate, slot) for slot in missing)),
            "multi_position": min(5.0, float(len(candidate.get("eligible_slots") or ()))) / 5.0,
            "balance_after": -pstdev(strengths_after) if len(strengths_after) > 1 else 0.0,
            "floor_after": min(strengths_after) if strengths_after else 0.0,
            "active_total": sum(
                _number(z_scores.get(category)) * active[category] for category in categories
            ),
        }
        for category in categories:
            value = _number(z_scores.get(category))
            gap = value - replacement[category]
            row[f"z::{category}"] = value
            row[f"active_z::{category}"] = value * active[category]
            row[f"need::{category}"] = value * max(0.0, -own[category])
            row[f"build::{category}"] = value * max(0.0, own[category])
            row[f"opponent_denial::{category}"] = value * max(0.0, opponent[category])
            row[f"replacement_gap::{category}"] = gap
            row[f"urgency::{category}"] = gap * min(2.0, picks_to_next / max(1.0, team_count))
        raw.append(row)
    normalized = [dict.fromkeys(names, 0.0) for _ in raw]
    for name in names:
        values = [_number(row.get(name)) for row in raw]
        mean = fmean(values) if values else 0.0
        scale = pstdev(values) if len(values) > 1 else 0.0
        scale = scale or 1.0
        for index, value in enumerate(values):
            normalized[index][name] = (value - mean) / scale
    return normalized


def _base_weights(categories, profile="balanced"):
    weights = dict.fromkeys(feature_names(categories), 0.0)
    weights.update({
        "general_z": 0.55, "gp": 0.18, "position_fit": 0.20,
        "late_position_fit": 1.10, "multi_position": 0.12,
        "balance_after": 0.16, "floor_after": 0.10, "active_total": 0.65,
    })
    for category in categories:
        weights[f"z::{category}"] = 0.12
        weights[f"active_z::{category}"] = 0.42
        weights[f"need::{category}"] = 0.16
        weights[f"build::{category}"] = 0.10
        weights[f"opponent_denial::{category}"] = 0.025
        weights[f"replacement_gap::{category}"] = 0.20
        weights[f"urgency::{category}"] = 0.18
    if profile == "balanced":
        weights["balance_after"] = 0.42
        weights["floor_after"] = 0.24
    elif profile == "stars":
        weights["general_z"] = 1.0
        weights["active_total"] = 0.35
    elif profile == "scarcity":
        for category in categories:
            weights[f"replacement_gap::{category}"] = 0.55
            weights[f"urgency::{category}"] = 0.45
    elif profile == "adaptive_punt":
        weights["balance_after"] = -0.08
        weights["active_total"] = 0.95
        for category in categories:
            weights[f"build::{category}"] = 0.24
            weights[f"need::{category}"] = 0.04
    return weights


def _genome(identity, weights, generation=0, parent=None, temperature=0.025):
    return {
        "id": identity, "generation": generation, "parent": parent,
        "temperature": float(temperature), "weights": dict(weights),
    }


def initial_population(categories, config):
    profiles = ("balanced", "stars", "scarcity", "adaptive_punt")
    rng = random.Random(config.seed)
    population = []
    for index in range(config.population_size):
        profile = profiles[index % len(profiles)]
        base = _base_weights(categories, profile)
        weights = {
            name: value + rng.gauss(0.0, config.mutation_sigma * 0.65)
            for name, value in base.items()
        }
        population.append(_genome(f"g0-{index:02d}-{profile}", weights))
    hall = [_genome(f"seed-{profile}", _base_weights(categories, profile), parent="fixed") for profile in profiles]
    return population, hall


def fixed_anchor_population(categories, config):
    """Build deterministic, market-free opponents for stable validation and diversity."""
    anchors = []
    for profile in ("balanced", "stars", "scarcity", "adaptive_punt"):
        anchors.append(_genome(
            f"anchor-{profile}", _base_weights(categories, profile), parent="fixed-anchor",
            temperature=0.0,
        ))
    for category in categories:
        specialist = _base_weights(categories, "balanced")
        specialist[f"z::{category}"] += 1.25
        specialist[f"active_z::{category}"] += 1.25
        specialist[f"build::{category}"] += 0.60
        anchors.append(_genome(
            f"anchor-specialist-{category}", specialist, parent="fixed-anchor", temperature=0.0,
        ))
        punt = _base_weights(categories, "adaptive_punt")
        punt[f"z::{category}"] -= 1.10
        punt[f"active_z::{category}"] -= 1.40
        punt[f"need::{category}"] -= 0.45
        anchors.append(_genome(
            f"anchor-punt-{category}", punt, parent="fixed-anchor", temperature=0.0,
        ))
    rng = random.Random(f"{config.seed}:fixed-anchors")
    names = feature_names(categories)
    while len(anchors) < config.anchor_pool_size:
        profile = ("balanced", "stars", "scarcity", "adaptive_punt")[len(anchors) % 4]
        weights = _base_weights(categories, profile)
        for name in names:
            if rng.random() < 0.45:
                weights[name] = max(-2.5, min(2.5, weights[name] + rng.gauss(0.0, 0.55)))
        anchors.append(_genome(
            f"anchor-diverse-{len(anchors):02d}", weights,
            parent="fixed-anchor", temperature=0.0,
        ))
    return anchors[:config.anchor_pool_size]


def score_candidates(genome, feature_rows, rng=None):
    temperature = _number(genome.get("temperature")) if rng is not None else 0.0
    weights = genome["weights"]
    return [
        sum(_number(row.get(name)) * _number(weight) for name, weight in weights.items())
        + (rng.gauss(0.0, temperature) if temperature else 0.0)
        for row in feature_rows
    ]


def rank_market_free_candidates(candidates, context, genome):
    candidates = list(candidates)
    rows = market_free_feature_rows(
        candidates,
        roster=context.roster,
        remaining=context.remaining,
        opponent_rosters=context.opponent_rosters,
        categories=context.categories,
        roster_slots=context.roster_slots,
        overall_pick=context.eval_pick,
        next_own_pick=context.next_own_pick,
        rounds=context.rounds,
        team_count=context.team_count,
    )
    scores = score_candidates(genome, rows)
    ranked = sorted(zip(candidates, scores), key=lambda item: (-item[1], str(_identity(item[0]))))
    return ranked


def rank_market_free_ensemble_candidates(candidates, context, genomes):
    """Aggregate independently evolved policies by mean normalized rank."""
    candidates = list(candidates)
    if not genomes:
        raise ValueError("Market-free ensemble has no genomes")
    rows = market_free_feature_rows(
        candidates,
        roster=context.roster,
        remaining=context.remaining,
        opponent_rosters=context.opponent_rosters,
        categories=context.categories,
        roster_slots=context.roster_slots,
        overall_pick=context.eval_pick,
        next_own_pick=context.next_own_pick,
        rounds=context.rounds,
        team_count=context.team_count,
    )
    totals = {_identity(candidate): 0.0 for candidate in candidates}
    member_weights = [max(0.0, _number(genome.get("ensemble_weight"), 1.0)) for genome in genomes]
    weight_total = sum(member_weights)
    if weight_total <= 0:
        raise ValueError("Market-free ensemble weights must contain a positive value")
    denominator = max(1, len(candidates) - 1)
    for genome, member_weight in zip(genomes, member_weights):
        scores = score_candidates(genome, rows)
        ranked = sorted(
            zip(candidates, scores), key=lambda item: (-item[1], str(_identity(item[0]))),
        )
        for rank, (candidate, _) in enumerate(ranked):
            totals[_identity(candidate)] += member_weight * (1.0 - rank / denominator)
    scale = weight_total
    return sorted(
        ((candidate, totals[_identity(candidate)] / scale) for candidate in candidates),
        key=lambda item: (-item[1], str(_identity(item[0]))),
    )


def _choose(genome, remaining, rosters, slot, overall, categories, roster_slots, config, rng):
    roster = rosters[slot]
    feasible = _feasible_pool(remaining, roster, config.rounds - len(roster), roster_slots)
    # The limit is value-based only; no ADP, Player Rater or market rank participates.
    ordered = sorted(
        feasible,
        key=lambda player: _number(player.get("general_z", player.get("total_z", 0))),
        reverse=True,
    )
    # Preserve category specialists without relying on any external draft rank.
    specialists = []
    per_category = max(3, config.candidate_limit // max(1, len(categories) * 3))
    for category in categories:
        specialists.extend(sorted(
            feasible,
            key=lambda player: _number((player.get("z_scores") or {}).get(category)),
            reverse=True,
        )[:per_category])
    candidates, seen = [], set()
    for player in [*ordered[:config.candidate_limit], *specialists]:
        identity = _identity(player)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(player)
    future = [pick for pick in snake_pick_numbers(slot, config.team_count, config.rounds) if pick >= overall]
    rows = market_free_feature_rows(
        candidates, roster=roster, remaining=remaining,
        opponent_rosters=[rows for team, rows in rosters.items() if team != slot],
        categories=categories, roster_slots=roster_slots, overall_pick=overall,
        next_own_pick=_next_turn_pick(future, 0), rounds=config.rounds,
        team_count=config.team_count,
    )
    scores = score_candidates(genome, rows, rng)
    return max(
        zip(candidates, scores), key=lambda item: (item[1], str(_identity(item[0])))
    )[0]


def play_population_draft(players, categories, roster_slots, config_dict, assignments, draft_seed):
    config = EvolutionConfig(**config_dict).validate()
    remaining = list(deepcopy(players))
    rosters = {slot: [] for slot in range(1, config.team_count + 1)}
    rng = random.Random(draft_seed)
    for overall in range(1, config.team_count * config.rounds + 1):
        if not remaining:
            break
        slot = _slot_at_pick(overall, config.team_count)
        candidate = _choose(
            assignments[slot], remaining, rosters, slot, overall,
            categories, roster_slots, config, rng,
        )
        rosters[slot].append(candidate)
        identity = _identity(candidate)
        remaining = [player for player in remaining if _identity(player) != identity]
    stressed = _stress_rosters(
        rosters, f"v6:{draft_seed}", config.projection_gp_stddev, config.projection_stat_stddev,
    )
    return [
        {
            "policy_id": assignments[slot]["id"], "slot": slot,
            **evaluate_projected_rosters(stressed, slot, categories),
        }
        for slot in rosters
    ]


def _schedule(population, hall, anchors, config, generation):
    rng = random.Random(f"{config.seed}:{generation}:schedule")
    assignments = []
    hall_count = min(config.hall_slots_per_draft, len(hall))
    anchor_count = min(config.anchor_slots_per_draft, len(anchors))
    current_slots = config.team_count - hall_count - anchor_count
    for draft in range(config.drafts_per_generation):
        rows = {}
        start = draft * current_slots
        for offset in range(current_slots):
            rows[offset + 1] = population[(start + offset) % len(population)]
        hall_sample = rng.sample(hall, hall_count)
        for offset, genome in enumerate(hall_sample, current_slots + 1):
            rows[offset] = genome
        anchor_sample = rng.sample(anchors, anchor_count)
        for offset, genome in enumerate(anchor_sample, current_slots + hall_count + 1):
            rows[offset] = genome
        ordered = list(rows.values())
        rng.shuffle(ordered)
        assignments.append({slot: ordered[slot - 1] for slot in range(1, config.team_count + 1)})
    return assignments


def _fitness(samples, config, categories):
    wins = [row["category_wins"] for row in samples]
    ranks = [row["league_rank"] for row in samples]
    tail_size = max(1, math.ceil(len(wins) * config.cvar_fraction))
    cvar = fmean(sorted(wins)[:tail_size])
    mean_wins = fmean(wins)
    downside = mean_wins - cvar
    mean_rank = fmean(ranks)
    top_four_fraction = sum(rank <= 4 for rank in ranks) / len(ranks)
    top_one_fraction = sum(rank == 1 for rank in ranks) / len(ranks)
    category_ranks = {
        category: fmean(row["category_ranks"][category] for row in samples)
        for category in categories
    }
    ordered_categories = sorted(categories, key=lambda category: (category_ranks[category], category))
    strongest = list(ordered_categories[:2])
    weakest = list(reversed(ordered_categories[-2:]))
    robust = (
        mean_wins
        - config.downside_weight * downside
        - config.league_rank_weight * (mean_rank - 1.0)
        + config.top_four_weight * top_four_fraction
        + config.top_one_weight * top_one_fraction
    )
    return {
        "games": len(samples), "mean_category_wins": mean_wins,
        "cvar_category_wins": cvar, "downside": downside,
        "mean_league_rank": mean_rank,
        "top_four_rate": 100.0 * top_four_fraction,
        "top_one_rate": 100.0 * top_one_fraction,
        "category_ranks": category_ranks,
        "niche": {"strongest": strongest, "weakest": weakest},
        "robust_fitness": robust,
    }


def _tournament_metrics(
    players, categories, roster_slots, population, hall, config, generation, drafts, anchors=(),
):
    schedule_config = EvolutionConfig(**{**asdict(config), "drafts_per_generation": drafts})
    assignments = _schedule(population, hall, anchors, schedule_config, generation)
    arguments = [
        (players, tuple(categories), tuple(roster_slots), asdict(config), rows,
         config.seed + generation * 100_003 + draft)
        for draft, rows in enumerate(assignments)
    ]
    if config.workers == 1:
        batches = [play_population_draft(*row) for row in arguments]
    else:
        batches = []
        with ProcessPoolExecutor(max_workers=config.workers) as executor:
            futures = [executor.submit(play_population_draft, *row) for row in arguments]
            for future in as_completed(futures):
                batches.append(future.result())
    samples = defaultdict(list)
    current_ids = {genome["id"] for genome in population}
    for batch in batches:
        for row in batch:
            if row["policy_id"] in current_ids:
                samples[row["policy_id"]].append(row)
    if set(samples) != current_ids:
        raise RuntimeError("Tournament schedule failed to evaluate every current policy")
    return {identity: _fitness(rows, config, categories) for identity, rows in samples.items()}


def _mutate(parent, identity, generation, config, rng):
    weights = {}
    for name, value in parent["weights"].items():
        changed = value
        if rng.random() < config.mutation_probability:
            changed += rng.gauss(0.0, config.mutation_sigma)
        weights[name] = max(-3.0, min(3.0, changed))
    temperature = max(0.0, min(0.12, _number(parent.get("temperature", 0.025)) + rng.gauss(0.0, 0.008)))
    return _genome(identity, weights, generation, parent["id"], temperature)


def _next_population(population, metrics, generation, config):
    ranked = sorted(population, key=lambda row: metrics[row["id"]]["robust_fitness"], reverse=True)
    selected = list(ranked[:config.elite_count])
    seen_ids = {row["id"] for row in selected}
    seen_niches = {
        tuple(metrics[row["id"]]["niche"]["weakest"])
        for row in selected
    }
    if config.niche_elite_count:
        for row in ranked:
            niche = tuple(metrics[row["id"]]["niche"]["weakest"])
            if row["id"] in seen_ids or niche in seen_niches:
                continue
            selected.append(row)
            seen_ids.add(row["id"])
            seen_niches.add(niche)
            if len(selected) >= config.elite_count + config.niche_elite_count:
                break
    next_rows = [deepcopy(row) for row in selected]
    rng = random.Random(f"{config.seed}:{generation}:mutation")
    parents = list(selected)
    parent_ids = {parent["id"] for parent in parents}
    for row in ranked:
        if row["id"] not in parent_ids:
            parents.append(row)
            parent_ids.add(row["id"])
        if len(parents) >= config.parent_pool:
            break
    while len(next_rows) < config.population_size:
        parent = parents[rng.randrange(len(parents))]
        next_rows.append(_mutate(
            parent, f"g{generation + 1}-{len(next_rows):02d}", generation + 1, config, rng,
        ))
    return next_rows, ranked[0]


def _fingerprint(players, categories, roster_slots, config):
    payload = {
        "players": players, "categories": list(categories),
        "roster_slots": list(roster_slots), "config": asdict(config),
        "engine": 2,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _early_stopping_status(history, config):
    """Return a record-based stop decision using comparable validation scores."""
    patience = config.early_stopping_patience
    if not patience or len(history) < max(config.early_stopping_min_generations, patience + 1):
        return False, 0, None
    best = -math.inf
    stale = 0
    best_generation = None
    for row in history:
        value = _number(row.get("validation", row["best"])["robust_fitness"], -math.inf)
        if value > best + config.early_stopping_min_delta:
            best = value
            stale = 0
            best_generation = row["generation"] + 1
        else:
            stale += 1
    return stale >= patience, stale, best_generation


def evolve_population(players, categories, roster_slots, config, output_dir):
    config.validate()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "evolution-state.json"
    fingerprint = _fingerprint(players, categories, roster_slots, config)
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != fingerprint:
            raise ValueError("Evolution inputs/config changed; existing state is preserved")
        population, hall = state["population"], state["hall_of_fame"]
        anchors = state.get("fixed_anchors") or fixed_anchor_population(categories, config)
        champion_archive = state.get("champion_archive", [])
        start_generation = int(state["completed_generations"])
        history = state["history"]
    else:
        population, hall = initial_population(categories, config)
        anchors = fixed_anchor_population(categories, config)
        champion_archive = []
        start_generation, history = 0, []
        _atomic_json(state_path, {
            "fingerprint": fingerprint, "completed_generations": 0,
            "population": population, "hall_of_fame": hall,
            "fixed_anchors": anchors, "champion_archive": champion_archive,
            "history": history,
        })
    stopped_early = False
    stop_reason = None
    for generation in range(start_generation, config.generations):
        metrics = _tournament_metrics(
            players, categories, roster_slots, population, hall, config,
            generation, config.drafts_per_generation, anchors,
        )
        population, champion = _next_population(population, metrics, generation, config)
        champion_snapshot = deepcopy(champion)
        champion_snapshot["id"] = f"hall-g{generation:03d}-{champion['id']}"
        champion_snapshot["source_policy_id"] = champion["id"]
        hall = [*hall, champion_snapshot][-config.hall_max_size:]
        best_metrics = metrics[champion["id"]]
        if config.validation_drafts:
            validation_config = EvolutionConfig(**{
                **asdict(config),
                "hall_slots_per_draft": 0,
                "anchor_slots_per_draft": config.team_count - 1,
            })
            validation_metrics = _tournament_metrics(
                players, categories, roster_slots, [champion_snapshot], [], validation_config,
                90_000, config.validation_drafts, anchors,
            )[champion_snapshot["id"]]
        else:
            validation_metrics = best_metrics
        archived_champion = deepcopy(champion_snapshot)
        archived_champion["validation_metrics"] = validation_metrics
        champion_archive.append(archived_champion)
        history.append({
            "generation": generation, "best_policy_id": champion["id"],
            "best": best_metrics,
            "validation": validation_metrics,
            "population_mean_fitness": fmean(row["robust_fitness"] for row in metrics.values()),
            "population": metrics,
        })
        state = {
            "fingerprint": fingerprint, "completed_generations": generation + 1,
            "population": population, "hall_of_fame": hall,
            "fixed_anchors": anchors, "champion_archive": champion_archive,
            "history": history,
        }
        _atomic_json(state_path, state)
        print(json.dumps({
            "generation": generation + 1, "total": config.generations,
            "champion": champion["id"], "fitness": round(best_metrics["robust_fitness"], 4),
            "validation_fitness": round(validation_metrics["robust_fitness"], 4),
            "mean_wins": round(best_metrics["mean_category_wins"], 4),
            "cvar": round(best_metrics["cvar_category_wins"], 4),
        }), flush=True)
        should_stop, stale_generations, best_generation = _early_stopping_status(history, config)
        if should_stop:
            stopped_early = True
            stop_reason = {
                "type": "fitness_plateau",
                "patience": config.early_stopping_patience,
                "min_delta": config.early_stopping_min_delta,
                "stale_generations": stale_generations,
                "best_generation": best_generation,
            }
            print(json.dumps({
                "early_stop": True,
                "completed_generations": len(history),
                "reason": stop_reason,
            }), flush=True)
            break
    # Select across the complete history using a fixed arena, then re-evaluate
    # the strongest validation candidates in a larger mixed tournament.
    ranked_archive = sorted(
        champion_archive,
        key=lambda row: row["validation_metrics"]["robust_fitness"],
        reverse=True,
    )
    finalists = [deepcopy(row) for row in ranked_archive[:min(config.finalist_count, len(ranked_archive))]]
    final_config = EvolutionConfig(**{
        **asdict(config), "hall_slots_per_draft": 0,
    })
    finalist_metrics = _tournament_metrics(
        players, categories, roster_slots, finalists, [], final_config,
        100_000, config.final_drafts, anchors,
    )
    champion = deepcopy(max(
        finalists, key=lambda row: finalist_metrics[row["id"]]["robust_fitness"],
    ))
    selected_metrics = finalist_metrics[champion["id"]]
    champion["id"] = "standard8-v6-market-free-champion"
    checkpoint = output / "checkpoint"
    if checkpoint.exists():
        manifest_path = checkpoint / "manifest.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        raise FileExistsError(f"Incomplete checkpoint exists: {checkpoint}")
    checkpoint.mkdir()
    _atomic_json(checkpoint / "genome.json", champion)
    manifest = {
        "model_version": 6,
        "experiment_version": "6.1",
        "policy_type": POLICY_TYPE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": "standard8",
        "categories": list(categories),
        "roster_slots": list(roster_slots),
        "input_fingerprint": fingerprint,
        "config": asdict(config),
        "completed_generations": len(history),
        "configured_generations": config.generations,
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
        "selected_source_policy_id": champion.get("source_policy_id"),
        "selection_scope": "all_generation_champions_via_fixed_validation_arena",
        "generation_champions_considered": len(champion_archive),
        "finalist_count": len(finalists),
        "selection_metrics": selected_metrics,
        "finalist_metrics": finalist_metrics,
        "candidate_limit": config.candidate_limit,
        "inference_candidate_limit": len(players),
        "uses_market_features": False,
        "uses_adp": False,
        "uses_player_rater": False,
        "training_method": "population_self_play_fixed_anchors_validation_archive_elitism_mutation_hall_of_fame_cvar",
        "metadata": {
            "research_only": True,
            "projection_fallback_only": all(
                player.get("stats_source") == "previous_season" for player in players
            ),
        },
        "artifact_sha256": {
            "genome.json": hashlib.sha256((checkpoint / "genome.json").read_bytes()).hexdigest(),
        },
    }
    _atomic_json(checkpoint / "manifest.json", manifest)
    return manifest


def _load_snapshot(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload["players"], tuple(payload["categories"]), tuple(payload["roster_slots"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--input-snapshot", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    config = EvolutionConfig(**json.loads(Path(args.config).read_text(encoding="utf-8"))).validate()
    players, categories, slots = _load_snapshot(args.input_snapshot)
    plan = {
        "operation": "market-free population self-play",
        "config": asdict(config), "players": len(players),
        "categories": list(categories), "output_dir": str(Path(args.output_dir).resolve()),
        "estimated_full_drafts": (
            config.generations * (config.drafts_per_generation + config.validation_drafts)
            + config.final_drafts
        ),
        "market_features": False, "auto_promote": False,
    }
    if not args.execute:
        print(json.dumps({"dry_run": True, "plan": plan}, indent=2))
        return 0
    manifest = evolve_population(players, categories, slots, config, args.output_dir)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
