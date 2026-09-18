"""Explicit offline CLI. Expensive or mutating commands require --execute."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sys
import time
from fastapi import HTTPException

from .dataset import dataset_summary
from .model import evaluate_checkpoint, train_market_expert, train_models
from .promotion import promote_checkpoint, promotion_decision
from .schema import TrainingConfig, categories_for_format


def _config(path, overrides):
    payload = {}
    if path:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload.update({key: value for key, value in overrides.items() if value is not None})
    if "behavior_policies" in payload:
        payload["behavior_policies"] = tuple(payload["behavior_policies"])
    return TrainingConfig(**payload).validate()


def _require_execute(args, plan):
    if args.execute:
        return
    print(json.dumps({"dry_run": True, "plan": plan}, indent=2, ensure_ascii=False))
    raise SystemExit(0)


def _optional_dataset_summary(path):
    source = Path(path)
    if not source.exists():
        return {"available": False, "path": str(source)}
    return {"available": True, **dataset_summary(source)}


def _optional_json(path):
    source = Path(path)
    if not source.exists():
        return None
    return json.loads(source.read_text(encoding="utf-8"))


def _resolved(path):
    return str(Path(path).resolve())


def _draft_inputs(args, config, attempts=4):
    """Fetch ESPN inputs with bounded retries for transient network failures."""
    snapshot_path = Path(args.input_snapshot) if getattr(args, "input_snapshot", None) else None
    if snapshot_path and snapshot_path.exists():
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if set(snapshot["categories"]) != set(categories_for_format(config.format_name)):
            raise ValueError("Input snapshot category format mismatch")
        if snapshot["team_count"] != config.team_count or snapshot["rounds"] != config.rounds:
            raise ValueError("Input snapshot league dimensions mismatch")
        return snapshot["players"], tuple(snapshot["categories"]), snapshot["roster_slots"]
    from web.backend.dependencies import get_league_meta
    from web.backend.services.draft import get_draft_recommendations
    from web.backend.services.draft_benchmark import prepare_players_for_categories
    from core.config import DEFAULT_TEAM_ID, PERIODS

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            get_league_meta.cache_clear()
            metadata = get_league_meta()
            if metadata.league is None:
                raise ConnectionError("ESPN league did not load")
            team_id = args.team_id or DEFAULT_TEAM_ID
            if team_id is None:
                raise ValueError("--team-id is required when DEFAULT_TEAM_ID is not configured")
            recommendations = get_draft_recommendations(
                metadata, team_id, PERIODS["projected"], (), 300, (), None, False, True,
            )
            categories = categories_for_format(config.format_name)
            players = prepare_players_for_categories(recommendations["players"], categories)
            if snapshot_path:
                payload = {
                    "players": players, "categories": list(categories),
                    "roster_slots": recommendations.get("roster_slots"),
                    "team_count": config.team_count, "rounds": config.rounds,
                    "league_id": metadata.league_id, "season": metadata.year,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "stats_source": recommendations.get("stats_source"),
                }
                snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = snapshot_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                temporary.replace(snapshot_path)
            return players, categories, recommendations.get("roster_slots")
        except (ConnectionError, OSError, AttributeError, HTTPException) as error:
            if isinstance(error, HTTPException) and error.status_code not in {429, 502, 503, 504}:
                raise
            last_error = error
            if attempt == attempts:
                break
            delay = 5 * attempt
            print(f"ESPN attempt {attempt}/{attempts} failed; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
    raise RuntimeError(f"Could not load ESPN draft inputs after {attempts} attempts") from last_error


def _validate_promotion_evidence(checkpoint, metrics, self_play):
    expected = _resolved(checkpoint)
    metric_checkpoint = (metrics.get("_provenance") or {}).get("checkpoint")
    benchmark_checkpoint = (self_play.get("_provenance") or {}).get("checkpoint")
    if metric_checkpoint != expected:
        raise ValueError("Evaluation report was not produced for this checkpoint")
    if benchmark_checkpoint != expected:
        raise ValueError("Self-play report was not produced for this checkpoint")
    if (metrics.get("_provenance") or {}).get("split") != "test":
        raise ValueError("Promotion requires evaluation on the test split")
    if self_play.get("benchmark_version", 0) < 2:
        raise ValueError("Old benchmark has invalid adaptive routing; rerun benchmark")
    manifest = json.loads((Path(checkpoint) / "manifest.json").read_text(encoding="utf-8"))
    manifest_hash = hashlib.sha256((Path(checkpoint) / "manifest.json").read_bytes()).hexdigest()
    for evidence in (metrics, self_play):
        supplied = (evidence.get("_provenance") or {}).get("checkpoint_manifest_sha256")
        if supplied is not None and supplied != manifest_hash:
            raise ValueError("Evidence checkpoint manifest checksum mismatch")
    metric_dataset_hash = (metrics.get("_provenance") or {}).get("dataset_sha256")
    if metric_dataset_hash is not None and metric_dataset_hash != manifest.get("dataset_sha256"):
        raise ValueError("Evaluation dataset does not match the checkpoint training dataset")
    if manifest.get("metadata", {}).get("legacy_resume_unverified"):
        raise ValueError("Legacy resumed data have no verified original input snapshot; manual research review required")
    if manifest.get("metadata", {}).get("projection_fallback_only"):
        raise ValueError("Checkpoint used only previous-season fallback stats; live promotion is forbidden")


def command_generate(args):
    config = _config(args.config, {
        "format_name": args.format,
        "episodes": args.episodes,
        "workers": args.workers,
        "candidate_count": args.candidates,
        "rollouts_per_candidate": args.rollouts,
        "policy_checkpoint": args.policy_checkpoint,
    })
    output = Path(args.output or config.output_path / f"{config.format_name}-dataset.jsonl.gz")
    start_episode = int(args.start_episode or 0)
    estimated_rows = (config.episodes - start_episode) * config.rounds * config.candidate_count
    _require_execute(args, {
        "operation": "generate counterfactual self-play dataset",
        "config": config.to_dict(),
        "output": str(output),
        "estimated_rows": estimated_rows,
        "start_episode": start_episode,
        "seed_dataset": args.seed_dataset,
    })
    from .simulation import generate_dataset

    if config.policy_checkpoint:
        policy_checkpoint = Path(config.policy_checkpoint)
        if not policy_checkpoint.exists():
            raise FileNotFoundError(f"Policy checkpoint not found: {policy_checkpoint}")
        config = replace(config, policy_checkpoint=str(policy_checkpoint.resolve()))

    players, categories, roster_slots = _draft_inputs(args, config)
    manifest = generate_dataset(
        players, categories, roster_slots, config, output,
        start_episode=start_episode,
        seed_dataset=args.seed_dataset,
        auto_resume=args.resume,
    )
    print(json.dumps({"summary": dataset_summary(output), "manifest": manifest}, indent=2))


def command_train(args):
    checkpoint = Path(args.checkpoint)
    dataset_manifest = _optional_json(str(args.dataset) + ".manifest.json") or {}
    stats_source_counts = dataset_manifest.get("stats_source_counts") or {}
    _require_execute(args, {
        "operation": "train value and policy models",
        "format": args.format,
        "dataset": args.dataset,
        "checkpoint": str(checkpoint),
        "dataset_summary": _optional_dataset_summary(args.dataset),
    })
    manifest = train_models(
        args.dataset,
        checkpoint,
        random_seed=args.seed,
        metadata={
            "command": "train", "format": args.format,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "legacy_resume_unverified": dataset_manifest.get("legacy_resume_unverified", True),
            "stats_source_counts": stats_source_counts,
            "projection_fallback_only": bool(stats_source_counts) and not stats_source_counts.get("selected_period", 0),
        },
    )
    print(json.dumps(manifest, indent=2))


def command_train_expert(args):
    checkpoint = Path(args.checkpoint)
    _require_execute(args, {
        "operation": "train policy-only market expert",
        "market_model": args.market_model,
        "dataset": args.dataset,
        "base_checkpoint": args.base_checkpoint,
        "checkpoint": str(checkpoint),
    })
    manifest = train_market_expert(
        args.dataset, args.base_checkpoint, checkpoint, args.market_model,
        random_seed=args.seed,
        metadata={
            "command": "train-expert", "format": args.format,
            "research_only": True,
        },
    )
    print(json.dumps(manifest, indent=2))


def command_evaluate(args):
    _require_execute(args, {
        "operation": "evaluate frozen checkpoint on holdout",
        "dataset": args.dataset,
        "checkpoint": args.checkpoint,
        "split": args.split,
    })
    metrics = evaluate_checkpoint(
        args.dataset, args.checkpoint, args.split, args.market_model,
    )
    metrics["_provenance"] = {
        "checkpoint": _resolved(args.checkpoint),
        "dataset": _resolved(args.dataset),
        "split": args.split,
        "market_model": args.market_model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest(),
        "checkpoint_manifest_sha256": hashlib.sha256(
            (Path(args.checkpoint) / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


def command_promote(args):
    metrics = _optional_json(args.metrics)
    self_play = _optional_json(args.self_play)
    if metrics is None or self_play is None:
        _require_execute(args, {
            "operation": "promote checkpoint if every gate passes",
            "checkpoint": args.checkpoint,
            "format": args.format,
            "name": args.name,
            "evidence_available": False,
        })
        raise FileNotFoundError("Evaluation and self-play reports are required")
    _validate_promotion_evidence(args.checkpoint, metrics, self_play)
    decision = promotion_decision(metrics, self_play)
    _require_execute(args, {
        "operation": "promote checkpoint if every gate passes",
        "checkpoint": args.checkpoint,
        "format": args.format,
        "name": args.name,
        "decision": decision,
    })
    destination = promote_checkpoint(args.checkpoint, args.champions, decision, args.name, args.format)
    print(json.dumps({"promoted": str(destination), "decision": decision}, indent=2))


def command_benchmark(args):
    _require_execute(args, {
        "operation": "population self-play benchmark for promotion evidence",
        "format": args.format,
        "runs_per_slot": args.runs_per_slot,
        "checkpoint": args.checkpoint,
        "learned_policy": not args.disable_learned_policy,
        "opponent_field": args.opponent_field,
        "market_model": args.market_model,
        "seed": args.seed,
        "output": args.output,
    })
    from web.backend.services.draft_benchmark import benchmark_adaptive_vs_legacy

    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if args.disable_learned_policy:
        os.environ.pop("DRAFT_MODEL_CHECKPOINT", None)
        os.environ["DRAFT_DISABLE_LEARNED"] = "1"
    else:
        os.environ.pop("DRAFT_DISABLE_LEARNED", None)
        os.environ["DRAFT_MODEL_CHECKPOINT"] = str(checkpoint.resolve())
    os.environ["DRAFT_ML_STRICT"] = "1"
    config = TrainingConfig(format_name=args.format, team_count=args.team_count, rounds=args.rounds)
    players, categories, roster_slots = _draft_inputs(args, config)
    report = benchmark_adaptive_vs_legacy(
        players, config.team_count, config.rounds, categories,
        roster_slots=roster_slots,
        runs_per_slot=args.runs_per_slot,
        opponent_field=args.opponent_field,
        market_model=args.market_model,
        seed=args.seed,
    )
    report["_provenance"] = {
        "checkpoint": _resolved(checkpoint),
        "format": args.format,
        "learned_policy": not args.disable_learned_policy,
        "opponent_field": args.opponent_field,
        "market_model": args.market_model,
        "seed": args.seed,
        "input_snapshot": _resolved(args.input_snapshot) if args.input_snapshot else None,
        "input_sha256": hashlib.sha256(Path(args.input_snapshot).read_bytes()).hexdigest() if args.input_snapshot else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checkpoint_manifest_sha256": hashlib.sha256(
            (checkpoint / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"report": str(destination), "paired_scenarios": report["paired_scenarios"]}, indent=2))


def parser():
    root = argparse.ArgumentParser(description="NBA Fantasy draft ML pipeline")
    commands = root.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate")
    generate.add_argument("--config")
    generate.add_argument("--format", choices=("standard8", "custom11"), default=None)
    generate.add_argument("--episodes", type=int)
    generate.add_argument("--workers", type=int)
    generate.add_argument("--candidates", type=int)
    generate.add_argument("--rollouts", type=int)
    generate.add_argument("--policy-checkpoint")
    generate.add_argument("--start-episode", type=int, default=0)
    generate.add_argument("--seed-dataset")
    generate.add_argument("--resume", action="store_true")
    generate.add_argument("--input-snapshot")
    generate.add_argument("--team-id", type=int)
    generate.add_argument("--output")
    generate.add_argument("--execute", action="store_true")
    generate.set_defaults(handler=command_generate)

    train = commands.add_parser("train")
    train.add_argument("--dataset", required=True)
    train.add_argument("--checkpoint", required=True)
    train.add_argument("--format", choices=("standard8", "custom11"), required=True)
    train.add_argument("--seed", type=int, default=260902)
    train.add_argument("--execute", action="store_true")
    train.set_defaults(handler=command_train)

    expert = commands.add_parser("train-expert")
    expert.add_argument("--dataset", required=True)
    expert.add_argument("--base-checkpoint", required=True)
    expert.add_argument("--checkpoint", required=True)
    expert.add_argument("--market-model", choices=("conservative", "espn_draft", "league_rater", "category_z"), required=True)
    expert.add_argument("--format", choices=("standard8",), default="standard8")
    expert.add_argument("--seed", type=int, default=260905)
    expert.add_argument("--execute", action="store_true")
    expert.set_defaults(handler=command_train_expert)

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--checkpoint", required=True)
    evaluate.add_argument("--split", choices=("validation", "test"), default="test")
    evaluate.add_argument("--market-model", choices=("conservative", "espn_draft", "league_rater", "category_z"))
    evaluate.add_argument("--output")
    evaluate.add_argument("--execute", action="store_true")
    evaluate.set_defaults(handler=command_evaluate)

    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--format", choices=("standard8", "custom11"), required=True)
    benchmark.add_argument("--runs-per-slot", type=int, default=20)
    benchmark.add_argument("--checkpoint", required=True)
    benchmark.add_argument("--disable-learned-policy", action="store_true")
    benchmark.add_argument("--opponent-field", choices=("mixed", "market", "human", "heuristic_mixed"), default="mixed")
    benchmark.add_argument("--seed", type=int, default=1204907)
    benchmark.add_argument("--market-model", choices=("espn_draft", "category_z", "league_rater", "conservative"), default="espn_draft")
    benchmark.add_argument("--input-snapshot")
    benchmark.add_argument("--team-count", type=int, default=10)
    benchmark.add_argument("--rounds", type=int, default=13)
    benchmark.add_argument("--team-id", type=int)
    benchmark.add_argument("--output", required=True)
    benchmark.add_argument("--execute", action="store_true")
    benchmark.set_defaults(handler=command_benchmark)

    promote = commands.add_parser("promote")
    promote.add_argument("--checkpoint", required=True)
    promote.add_argument("--metrics", required=True)
    promote.add_argument("--self-play", required=True)
    promote.add_argument("--champions", default="artifacts/draft_ml/champions")
    promote.add_argument("--format", choices=("standard8", "custom11"), required=True)
    promote.add_argument("--name", required=True)
    promote.add_argument("--execute", action="store_true")
    promote.set_defaults(handler=command_promote)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    args.handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
