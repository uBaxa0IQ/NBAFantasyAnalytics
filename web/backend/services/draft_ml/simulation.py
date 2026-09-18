"""Counterfactual population self-play dataset generation."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
from statistics import fmean

from core.projection import can_play_slot

from ..draft_benchmark import _feasible_pool, _identity, _population_profiles, _rank_value, _scenario, prepare_benchmark_market
from ..draft_evaluation import evaluate_projected_rosters
from ..draft_simulation import _next_turn_pick, _select_player, _slot_at_pick, snake_pick_numbers, unfilled_roster_slots
from ..draft_strategy import strategy_library, strategy_probabilities
from .dataset import dataset_summary, dataset_writer, read_records, split_for_scenario
from .features import extract_candidate_features
from .schema import TrainingConfig


DATASET_ENGINE_VERSION = 5


class DraftEnvironment:
    def __init__(self, players, categories, roster_slots, config, episode_seed, profile_offset=0):
        group = episode_seed // config.team_count
        self.market_model = config.market_models[group % len(config.market_models)]
        self.opponent_field = config.opponent_fields[(group // len(config.market_models)) % len(config.opponent_fields)]
        self.players = (deepcopy(players) if self.market_model == "snapshot" else
                        prepare_benchmark_market(deepcopy(players), categories, self.market_model))
        self.categories = tuple(categories)
        self.roster_slots = tuple(roster_slots or ())
        self.config = config
        self.episode_index = episode_seed
        self.overall = 1
        self.hero_slot = episode_seed % config.team_count + 1
        self.market, self.opponent_rank = _scenario(self.players, config.seed, episode_seed)
        self.remaining = {_identity(player): player for player in self.players}
        self.rosters = {slot: [] for slot in range(1, config.team_count + 1)}
        base_profiles = _population_profiles(config.team_count, self.categories, self.opponent_field)
        self.profiles = {
            slot: base_profiles[(slot - 1 + profile_offset) % config.team_count + 1]
            for slot in range(1, config.team_count + 1)
        }

    def clone(self):
        if self.config.experiment_id:
            # Isolate score annotations between counterfactual candidate rollouts.
            return deepcopy(self)
        clone = object.__new__(DraftEnvironment)
        clone.players = self.players
        clone.categories = self.categories
        clone.roster_slots = self.roster_slots
        clone.config = self.config
        clone.episode_index = self.episode_index
        clone.market_model = self.market_model
        clone.opponent_field = self.opponent_field
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
        if policy in {"model", "adaptive", "adaptive_heuristic"}:
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
                policy_mode={"model": "legacy", "adaptive": "adaptive", "adaptive_heuristic": "adaptive_heuristic"}[policy],
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


def _candidate_pool(environment, count, required=()):
    market = environment.market_order()
    value = sorted(
        environment.remaining.values(),
        key=lambda player: player.get("general_z", player.get("total_z", 0)),
        reverse=True,
    )
    required = [
        player for player in required
        if player is not None and _identity(player) in environment.remaining
    ]
    combined = required + [player for _, player in market[:count * 2]] + value[:count * 2]
    if environment.config.candidate_pool == "balanced":
        # Round-robin prevents the market prefix from consuming the entire pool.
        interleaved = [player for pair in zip([p for _, p in market], value) for player in pair]
        combined = required + interleaved
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


def _behavior_profile(behavior, categories):
    if behavior == "adaptive":
        return None
    best_fixed = max(
        strategy_library(categories), key=lambda row: row.get("prior_delta", 0.0),
    )["punt_categories"]
    profiles = {
        "legacy_balanced": {"policy": "model", "punts": ()},
        "legacy_fixed": {"policy": "model", "punts": best_fixed},
        "roto": {"policy": "roto", "punts": ()},
        "adp": {"policy": "adp", "punts": ()},
    }
    return profiles[behavior]


def _strategy_entropy(roster, candidate, categories, rounds):
    probabilities = strategy_probabilities([*roster, candidate], categories, rounds)
    return -sum(
        row["probability"] * math.log(max(row["probability"], 1e-12))
        for row in probabilities
    )


def split_for_episode(config, episode_index):
    """Keep every market/field cell at an exact 80/10/10 episode split."""
    if not config.experiment_id:
        return split_for_scenario(f"{config.format_name}:{episode_index}")
    group = episode_index // config.team_count
    combination_count = len(config.market_models) * len(config.opponent_fields)
    combination = group % combination_count
    repetition = group // combination_count
    hero_slot = episode_index % config.team_count + 1
    validation_slot = (combination + repetition) % config.team_count + 1
    test_slot = (
        combination + repetition + max(1, config.team_count // 2)
    ) % config.team_count + 1
    if hero_slot == validation_slot:
        return "validation"
    if hero_slot == test_slot:
        return "test"
    return "train"


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
        f"{config.seed}:{str(environment.episode_index) + ':' if config.experiment_id else ''}{environment.hero_slot}:{environment.overall}:{rollout_index}",
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
    behavior_index = episode_index // config.team_count if config.experiment_id else episode_index
    behavior = config.behavior_policies[behavior_index % len(config.behavior_policies)]
    scenario_id = f"{config.format_name}:{config.experiment_id + ':' if config.experiment_id else ''}{episode_index}"
    episode_split = split_for_episode(config, episode_index)
    records = []
    while not environment.complete_draft:
        environment.advance_to_hero()
        if environment.complete_draft:
            break
        roster = environment.rosters[environment.hero_slot]
        behavior_profile = _behavior_profile(behavior, categories)
        behavior_player = (
            environment.choose(environment.hero_slot, behavior_profile)
            if behavior_profile is not None else None
        )
        # A behavior-policy action must be represented in its counterfactual state.
        # Otherwise the old fallback silently relabelled the reward-optimal action as
        # ROTO/ADP/legacy behavior and corrupted the exploration distribution.
        candidates = _candidate_pool(
            environment, config.candidate_count, required=(behavior_player,),
        )
        remaining = list(environment.remaining.values())
        opponents = [environment.rosters[slot] for slot in environment.rosters if slot != environment.hero_slot]
        strategies = strategy_probabilities(roster, categories, config.rounds)
        future = environment._future_picks(environment.hero_slot)
        state_id = f"{scenario_id}:{environment.overall}"
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
            entropy = _strategy_entropy(roster, candidate, categories, config.rounds)
            reward = (
                config.reward_weights["category_wins"] * mean_wins
                + config.reward_weights["league_rank"] * fmean(ranks)
                + config.reward_weights["downside"] * downside
                + config.reward_weights["flexibility"] * entropy
            )
            candidate_rows.append({
                "scenario_id": scenario_id,
                "market_model": environment.market_model,
                "opponent_field": environment.opponent_field,
                "split": episode_split,
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
                    "flexibility_entropy": entropy,
                    "reward": reward,
                    "is_best": 0,
                },
            })
        best = max(candidate_rows, key=lambda row: row["labels"]["reward"])
        best["labels"]["is_best"] = 1
        if behavior == "adaptive":
            chosen_row = best if rng.random() >= 0.15 else rng.choice(candidate_rows)
        else:
            chosen_row = next(
                (row for row in candidate_rows if row["candidate_id"] == _identity(behavior_player)),
                None,
            )
            if chosen_row is None:
                raise RuntimeError(f"Behavior action missing from candidate pool: {behavior}")
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


def _normalized_config(config):
    payload = config.to_dict()
    payload.pop("workers", None)
    payload.pop("output_dir", None)
    # Normalize tuples to their JSON representation so persisted manifests can
    # be compared with the in-memory dataclass without false mismatches.
    return json.loads(json.dumps(payload, sort_keys=True))


def _input_hash(players, categories, roster_slots):
    return hashlib.sha256(json.dumps(
        {"players": players, "categories": list(categories), "slots": list(roster_slots or ())},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _validate_completed_dataset(output_path, manifest, config, input_hash):
    manifest_config = dict(manifest.get("config") or {})
    manifest_config.pop("workers", None)
    manifest_config.pop("output_dir", None)
    if (
        manifest.get("engine_version") != DATASET_ENGINE_VERSION
        or manifest.get("input_sha256") != input_hash
        or manifest_config != _normalized_config(config)
    ):
        raise ValueError("Completed dataset does not match current input/config/engine")
    if manifest.get("dataset_sha256") != hashlib.sha256(output_path.read_bytes()).hexdigest():
        raise ValueError("Completed dataset checksum mismatch")
    summary = dataset_summary(output_path)  # Also verifies the whole gzip/jsonl stream.
    if summary["states"] != config.episodes * config.rounds:
        raise ValueError("Completed dataset has an unexpected state count")
    return manifest


def generate_dataset(
    players, categories, roster_slots, config: TrainingConfig, output_path,
    *, start_episode=0, seed_dataset=None, auto_resume=False,
):
    """Generate counterfactual rows. This is the expensive operation called by CLI."""
    config.validate()
    output_path = Path(output_path)
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    input_hash = _input_hash(players, categories, roster_slots)
    if auto_resume and output_path.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return _validate_completed_dataset(output_path, manifest, config, input_hash)
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Dataset version already exists: {output_path}")
    start_episode = int(start_episode or 0)
    if start_episode < 0 or start_episode >= config.episodes:
        raise ValueError("start_episode must be between 0 and episodes - 1")
    if start_episode and not seed_dataset:
        raise ValueError("seed_dataset is required when resuming")
    seed_records = _validated_seed_records(seed_dataset, config, start_episode) if start_episode and not auto_resume else []
    temporary_dataset = output_path.with_name(output_path.name + ".partial")
    if output_path.suffix == ".gz":
        temporary_dataset = output_path.with_name(output_path.name + ".partial.gz")
    journal = output_path.with_name(output_path.name + ".episodes")
    journal.mkdir(parents=True, exist_ok=True)
    contract_config = _normalized_config(config)
    contract = {
        "config": contract_config,
        "input_sha256": input_hash,
        "engine_version": DATASET_ENGINE_VERSION,
    }
    contract_path = journal / "run.json"
    old_contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else None
    if old_contract and any(old_contract.get(key) != value for key, value in contract.items()):
        raise ValueError("Resume input snapshot/config changed; existing episode journal is preserved")
    completed = {}
    legacy_unverified = bool(seed_records)
    if auto_resume:
        for source in (seed_dataset, temporary_dataset):
            if source and Path(source).exists():
                recovered = recover_complete_episodes(source, config)
                completed.update(recovered)
                legacy_unverified = legacy_unverified or bool(recovered)
    elif seed_records:
        for record in seed_records:
            episode = int(record["scenario_id"].rsplit(":", 1)[1])
            completed.setdefault(episode, []).append(record)
    for path in journal.glob("episode-*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        completed[payload["episode"]] = payload["records"]
    legacy_unverified = (old_contract or {}).get("legacy_resume_unverified", legacy_unverified)
    contract["legacy_resume_unverified"] = legacy_unverified
    if not old_contract:
        _atomic_json(contract_path, contract)
    progress_path = output_path.with_name(output_path.name + ".progress.json")
    _atomic_json(progress_path, {"completed": len(completed), "total": config.episodes, "last_episode": None})

    def save_episode(episode, batch):
        _atomic_json(journal / f"episode-{episode:05d}.json", {"episode": episode, "records": batch})
        completed[episode] = batch
        progress = {"completed": len(completed), "total": config.episodes, "last_episode": episode}
        _atomic_json(progress_path, progress)
        print(json.dumps({"progress": progress}), flush=True)

    for episode, batch in list(completed.items()):
        save_episode(episode, batch)
    pending = [episode for episode in range(config.episodes) if episode not in completed]
    print(json.dumps({"resumed_episodes": len(completed), "remaining_episodes": len(pending)}), flush=True)
    if config.workers == 1:
        for episode in pending:
            save_episode(episode, generate_episode(players, categories, roster_slots, config.to_dict(), episode))
    elif pending:
        executor = ProcessPoolExecutor(max_workers=config.workers)
        try:
            futures = {
                executor.submit(generate_episode, players, tuple(categories), tuple(roster_slots or ()), config.to_dict(), episode): episode
                for episode in pending
            }
            for future in as_completed(futures):
                save_episode(futures[future], future.result())
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
    if temporary_dataset.exists():
        backup = temporary_dataset.with_name(temporary_dataset.name + ".backup-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
        temporary_dataset.replace(backup)
    with dataset_writer(temporary_dataset) as write:
        for episode in range(config.episodes):
            for record in completed[episode]:
                write(record)
    temporary_dataset.replace(output_path)
    identities = sorted(str(_identity(player)) for player in players)
    population_hash = hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()
    manifest = {
        "dataset_version": 2,
        "engine_version": DATASET_ENGINE_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(output_path.resolve()),
        "format": config.format_name,
        "categories": list(categories),
        "roster_slots": list(roster_slots or ()),
        "player_count": len(players),
        "stats_source_counts": dict(Counter(
            str(player.get("stats_source") or "unknown") for player in players
        )),
        "player_population_sha256": population_hash,
        "policy_checkpoint": config.policy_checkpoint,
        "resumed_from_episode": start_episode,
        "seed_dataset": str(Path(seed_dataset).resolve()) if seed_dataset else None,
        "legacy_resume_unverified": legacy_unverified,
        "input_sha256": input_hash,
        "dataset_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "config": config.to_dict(),
    }
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)
    return manifest


def _episode_from_tuple(arguments):
    return generate_episode(*arguments)


def _atomic_json(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def recover_complete_episodes(path, config):
    """Recover complete JSONL states even when the final gzip member is truncated."""
    groups = {}
    try:
        for record in read_records(path):
            scenario = str(record.get("scenario_id", ""))
            if not scenario.startswith(config.format_name + ":"):
                continue
            episode = int(scenario.rsplit(":", 1)[1])
            if 0 <= episode < config.episodes:
                groups.setdefault(episode, []).append(record)
    except (EOFError, OSError, ValueError):
        pass  # Only complete, validated episodes below are retained.
    complete = {}
    for episode, rows in groups.items():
        if episode == max(groups):
            # Legacy streams have no episode commit marker. The final episode
            # may lack an unselected candidate despite having best/selected rows.
            continue
        states = {}
        for row in rows:
            states.setdefault(row["state_id"], []).append(row)
        if len(states) != config.rounds:
            continue
        if all(
            2 <= len(items) <= config.candidate_count
            and len({item["candidate_id"] for item in items}) == len(items)
            and sum(item["labels"].get("is_best", 0) for item in items) == 1
            and sum(item["labels"].get("selected_by_behavior", 0) for item in items) == 1
            for items in states.values()
        ):
            complete[episode] = rows
    return complete
