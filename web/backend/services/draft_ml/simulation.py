"""Counterfactual population self-play dataset generation."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
from statistics import fmean

from core.projection import can_play_slot

from ..draft_benchmark import _feasible_pool, _identity, _population_profiles, _rank_value, _scenario
from ..draft_evaluation import evaluate_projected_rosters
from ..draft_simulation import _next_turn_pick, _select_player, _slot_at_pick, snake_pick_numbers, unfilled_roster_slots
from ..draft_strategy import strategy_library, strategy_probabilities
from .dataset import dataset_writer, read_records
from .features import extract_candidate_features
from .schema import TrainingConfig


class DraftEnvironment:
    def __init__(self, players, categories, roster_slots, config, episode_seed, profile_offset=0):
        self.players = list(players)
        self.categories = tuple(categories)
        self.roster_slots = tuple(roster_slots or ())
        self.config = config
        self.overall = 1
        self.hero_slot = episode_seed % config.team_count + 1
        self.market, self.opponent_rank = _scenario(self.players, config.seed, episode_seed)
        self.remaining = {_identity(player): player for player in self.players}
        self.rosters = {slot: [] for slot in range(1, config.team_count + 1)}
        base_profiles = _population_profiles(config.team_count, self.categories)
        self.profiles = {
            slot: base_profiles[(slot - 1 + profile_offset) % config.team_count + 1]
            for slot in range(1, config.team_count + 1)
        }

    def clone(self):
        clone = object.__new__(DraftEnvironment)
        clone.players = self.players
        clone.categories = self.categories
        clone.roster_slots = self.roster_slots
        clone.config = self.config
        clone.overall = self.overall
        clone.hero_slot = self.hero_slot
        clone.market = self.market
        clone.opponent_rank = self.opponent_rank
        clone.remaining = dict(self.remaining)
        clone.rosters = {slot: list(roster) for slot, roster in self.rosters.items()}
        clone.profiles = {slot: dict(profile) for slot, profile in self.profiles.items()}
        return clone

    @property
    def complete_draft(self):
        return self.overall > self.config.team_count * self.config.rounds or not self.remaining

    def market_order(self):
        return sorted(
            ([self.market[identity], player] for identity, player in self.remaining.items()),
            key=lambda item: item[0],
        )

    def _future_picks(self, slot):
        return [
            pick for pick in snake_pick_numbers(slot, self.config.team_count, self.config.rounds)
            if pick >= self.overall
        ]

    def choose(self, slot, profile):
        roster = self.rosters[slot]
        future_picks = self._future_picks(slot)
        market_order = self.market_order()
        policy = profile.get("policy", "roto")
        if policy in {"model", "adaptive"}:
            return _select_player(
                market_order,
                roster,
                self.overall,
                len(future_picks),
                next_own_pick=_next_turn_pick(future_picks, 0),
                punt_categories=tuple(profile.get("punts") or ()),
                opponent_rosters=[self.rosters[item] for item in self.rosters if item != slot],
                rounds=self.config.rounds,
                team_count=self.config.team_count,
                roster_slots=self.roster_slots,
                categories=self.categories,
                policy_mode="adaptive" if policy == "adaptive" else "legacy",
            )
        candidates = _feasible_pool(
            self.remaining.values(), roster, self.config.rounds - len(roster), self.roster_slots,
        )
        field = "espn_adp" if policy == "adp" else "espn_roto_rank"
        return min(candidates, key=lambda player: (
            _rank_value(player, field), self.opponent_rank[_identity(player)],
        ))

    def apply(self, player):
        slot = _slot_at_pick(self.overall, self.config.team_count)
        self.rosters[slot].append(player)
        self.remaining.pop(_identity(player), None)
        self.overall += 1

    def advance_to_hero(self):
        while not self.complete_draft and _slot_at_pick(self.overall, self.config.team_count) != self.hero_slot:
            slot = _slot_at_pick(self.overall, self.config.team_count)
            self.apply(self.choose(slot, self.profiles[slot]))

    def finish(self, hero_policy="adaptive"):
        while not self.complete_draft:
            slot = _slot_at_pick(self.overall, self.config.team_count)
            profile = self.profiles[slot]
            if slot == self.hero_slot:
                profile = {
                    "policy": "adaptive" if hero_policy == "adaptive" else "model",
                    "punts": () if hero_policy != "legacy_fixed" else profile.get("punts", ()),
                }
            self.apply(self.choose(slot, profile))
        return self.rosters


def _candidate_pool(environment, count):
    market = environment.market_order()
    value = sorted(
        environment.remaining.values(),
        key=lambda player: player.get("general_z", player.get("total_z", 0)),
        reverse=True,
    )
    combined = [player for _, player in market[:count * 2]] + value[:count * 2]
    missing = tuple(unfilled_roster_slots(environment.rosters[environment.hero_slot], environment.roster_slots))
    future = environment._future_picks(environment.hero_slot)
    if missing and len(future) <= len(missing):
        feasible = [player for player in combined if any(can_play_slot(player, slot) for slot in missing)]
        if feasible:
            combined = feasible
    result, seen = [], set()
    for player in combined:
        identity = _identity(player)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(player)
        if len(result) >= count:
            break
    return result


def _stress_rosters(rosters, seed, gp_stddev, stat_stddev):
    stressed = {}
    for slot, roster in rosters.items():
        stressed[slot] = []
        for player in roster:
            identity = _identity(player)
            stats = dict(player.get("stats") or {})
            changed = dict(stats)
            gp = float(stats.get("GP", 65) or 0)
            changed["GP"] = max(0.0, min(82.0, gp * max(0.5, random.Random(f"{seed}:{identity}:GP").gauss(1.0, gp_stddev))))
            for key, value in stats.items():
                if key in {"GP", "FG%", "FT%", "3PT%", "A/TO"} or not isinstance(value, (int, float)):
                    continue
                changed[key] = max(0.0, float(value) * max(0.55, random.Random(f"{seed}:{identity}:{key}").gauss(1.0, stat_stddev)))
            for made, attempted in (("FGM", "FGA"), ("FTM", "FTA"), ("3PM", "3PA")):
                if made in changed and attempted in changed:
                    changed[made] = min(changed[made], changed[attempted])
            stressed[slot].append({**player, "stats": changed, "games_played": changed["GP"]})
    return stressed


def _rollout(environment, candidate, rollout_index, config):
    branch = environment.clone()
    branch.apply(candidate)
    branch.profiles = {
        slot: branch.profiles[(slot - 1 + rollout_index) % config.team_count + 1]
        for slot in range(1, config.team_count + 1)
    }
    rosters = branch.finish("adaptive")
    stressed = _stress_rosters(
        rosters,
        f"{config.seed}:{environment.hero_slot}:{environment.overall}:{rollout_index}",
        config.projection_gp_stddev,
        config.projection_stat_stddev,
    )
    return evaluate_projected_rosters(stressed, environment.hero_slot, environment.categories)


def generate_episode(players, categories, roster_slots, config_dict, episode_index):
    config = TrainingConfig(**config_dict).validate()
    if config.policy_checkpoint:
        os.environ["DRAFT_MODEL_CHECKPOINT"] = config.policy_checkpoint
    else:
        os.environ.pop("DRAFT_MODEL_CHECKPOINT", None)
    environment = DraftEnvironment(players, categories, roster_slots, config, episode_index)
    rng = random.Random(config.seed + episode_index * 7919)
    behavior = config.behavior_policies[episode_index % len(config.behavior_policies)]
    records = []
    while not environment.complete_draft:
        environment.advance_to_hero()
        if environment.complete_draft:
            break
        candidates = _candidate_pool(environment, config.candidate_count)
        roster = environment.rosters[environment.hero_slot]
        remaining = list(environment.remaining.values())
        opponents = [environment.rosters[slot] for slot in environment.rosters if slot != environment.hero_slot]
        strategies = strategy_probabilities(roster, categories, config.rounds)
        future = environment._future_picks(environment.hero_slot)
        state_id = f"{config.format_name}:{episode_index}:{environment.overall}"
        candidate_rows = []
        for candidate in candidates:
            outcomes = [
                _rollout(environment, candidate, rollout, config)
                for rollout in range(config.rollouts_per_candidate)
            ]
            wins = [row["category_wins"] for row in outcomes]
            ranks = [row["league_rank"] for row in outcomes]
            mean_wins = fmean(wins)
            worst = sorted(wins)[max(0, math.ceil(len(wins) * 0.1) - 1)]
            downside = mean_wins - worst
            entropy = -sum(row["probability"] * math.log(max(row["probability"], 1e-12)) for row in strategies)
            reward = (
                config.reward_weights["category_wins"] * mean_wins
                + config.reward_weights["league_rank"] * fmean(ranks)
                + config.reward_weights["downside"] * downside
                + config.reward_weights["flexibility"] * entropy
            )
            candidate_rows.append({
                "scenario_id": f"{config.format_name}:{episode_index}",
                "state_id": state_id,
                "candidate_id": _identity(candidate),
                "candidate_name": candidate.get("name"),
                "features": extract_candidate_features(
                    roster=roster,
                    remaining=remaining,
                    candidate=candidate,
                    opponent_rosters=opponents,
                    categories=categories,
                    roster_slots=roster_slots,
                    overall_pick=environment.overall,
                    next_own_pick=_next_turn_pick(future, 0),
                    rounds=config.rounds,
                    team_count=config.team_count,
                    strategy_rows=strategies,
                ),
                "labels": {
                    "expected_category_wins": mean_wins,
                    "expected_league_rank": fmean(ranks),
                    "downside": downside,
                    "reward": reward,
                    "is_best": 0,
                },
            })
        best = max(candidate_rows, key=lambda row: row["labels"]["reward"])
        best["labels"]["is_best"] = 1
        if behavior == "adaptive":
            chosen_row = best if rng.random() >= 0.15 else rng.choice(candidate_rows)
        else:
            best_fixed = max(
                strategy_library(categories), key=lambda row: row.get("prior_delta", 0.0),
            )["punt_categories"]
            profile = {
                "legacy_balanced": {"policy": "model", "punts": ()},
                "legacy_fixed": {"policy": "model", "punts": best_fixed},
                "roto": {"policy": "roto", "punts": ()},
                "adp": {"policy": "adp", "punts": ()},
            }.get(behavior, {"policy": "adaptive", "punts": ()})
            behavior_player = environment.choose(environment.hero_slot, profile)
            chosen_row = next(
                (row for row in candidate_rows if row["candidate_id"] == _identity(behavior_player)),
                best,
            )
        chosen_row["labels"]["selected_by_behavior"] = 1
        chosen_row["labels"]["behavior_policy"] = behavior
        chosen = environment.remaining[chosen_row["candidate_id"]]
        records.extend(candidate_rows)
        environment.apply(chosen)
    return records


def _validated_seed_records(path, config, start_episode):
    """Return only a complete contiguous prefix of immutable prior episodes."""
    by_episode = {}
    prefix = f"{config.format_name}:"
    for record in read_records(path):
        scenario_id = str(record.get("scenario_id", ""))
        if not scenario_id.startswith(prefix):
            continue
        try:
            episode = int(scenario_id.rsplit(":", 1)[1])
        except (TypeError, ValueError):
            continue
        if episode < start_episode:
            by_episode.setdefault(episode, []).append(record)
    for episode in range(start_episode):
        rows = by_episode.get(episode, ())
        states = {}
        for record in rows:
            states.setdefault(record.get("state_id"), []).append(record)
        complete = len(states) == config.rounds and all(
            len(state_rows) >= 2
            and sum(int(row.get("labels", {}).get("is_best", 0)) for row in state_rows) == 1
            and sum(int(row.get("labels", {}).get("selected_by_behavior", 0)) for row in state_rows) == 1
            for state_rows in states.values()
        )
        if not complete:
            raise ValueError(
                f"Seed dataset episode {episode} is incomplete: {len(rows)} rows, {len(states)} states"
            )
    return [record for episode in range(start_episode) for record in by_episode[episode]]


def generate_dataset(
    players, categories, roster_slots, config: TrainingConfig, output_path,
    *, start_episode=0, seed_dataset=None,
):
    """Generate counterfactual rows. This is the expensive operation called by CLI."""
    config.validate()
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Dataset version already exists: {output_path}")
    start_episode = int(start_episode or 0)
    if start_episode < 0 or start_episode >= config.episodes:
        raise ValueError("start_episode must be between 0 and episodes - 1")
    if start_episode and not seed_dataset:
        raise ValueError("seed_dataset is required when resuming")
    seed_records = _validated_seed_records(seed_dataset, config, start_episode) if start_episode else []
    temporary_dataset = output_path.with_name(output_path.name + ".partial")
    if output_path.suffix == ".gz":
        temporary_dataset = output_path.with_name(output_path.name + ".partial.gz")
    if temporary_dataset.exists():
        temporary_dataset.unlink()
    arguments = [
        (players, tuple(categories), tuple(roster_slots or ()), config.to_dict(), episode)
        for episode in range(start_episode, config.episodes)
    ]
    try:
        with dataset_writer(temporary_dataset) as write:
            for record in seed_records:
                write(record)
            if config.workers == 1:
                batches = (generate_episode(*args) for args in arguments)
            else:
                executor = ProcessPoolExecutor(max_workers=config.workers)
                batches = executor.map(_episode_from_tuple, arguments)
            for batch in batches:
                for record in batch:
                    write(record)
            if config.workers != 1:
                executor.shutdown(wait=True, cancel_futures=False)
        temporary_dataset.replace(output_path)
    except Exception:
        if config.workers != 1 and "executor" in locals():
            executor.shutdown(wait=False, cancel_futures=True)
        if temporary_dataset.exists():
            temporary_dataset.unlink()
        raise
    identities = sorted(str(_identity(player)) for player in players)
    population_hash = hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()
    manifest = {
        "dataset_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(output_path.resolve()),
        "format": config.format_name,
        "categories": list(categories),
        "roster_slots": list(roster_slots or ()),
        "player_count": len(players),
        "player_population_sha256": population_hash,
        "policy_checkpoint": config.policy_checkpoint,
        "resumed_from_episode": start_episode,
        "seed_dataset": str(Path(seed_dataset).resolve()) if seed_dataset else None,
        "config": config.to_dict(),
    }
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def _episode_from_tuple(arguments):
    return generate_episode(*arguments)
