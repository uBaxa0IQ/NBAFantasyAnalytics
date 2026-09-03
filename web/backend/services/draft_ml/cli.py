"""Explicit offline CLI. Expensive or mutating commands require --execute."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

from .dataset import dataset_summary
from .model import evaluate_checkpoint, train_models
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
            return players, categories, recommendations.get("roster_slots")
        except (ConnectionError, OSError, AttributeError) as error:
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
    )
    print(json.dumps({"summary": dataset_summary(output), "manifest": manifest}, indent=2))


def command_train(args):
    checkpoint = Path(args.checkpoint)
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
    metrics = evaluate_checkpoint(args.dataset, args.checkpoint, args.split)
    metrics["_provenance"] = {
        "checkpoint": _resolved(args.checkpoint),
        "dataset": _resolved(args.dataset),
        "split": args.split,
        "created_at": datetime.now(timezone.utc).isoformat(),
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
        "output": args.output,
    })
    from web.backend.dependencies import get_league_meta
    from web.backend.services.draft import get_draft_recommendations
    from web.backend.services.draft_benchmark import benchmark_adaptive_vs_legacy
    from core.config import DEFAULT_TEAM_ID, PERIODS

    checkpoint = Path(args.checkpoint)
    if not checkpoint.exists():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    if args.disable_learned_policy:
        os.environ.pop("DRAFT_MODEL_CHECKPOINT", None)
    else:
        os.environ["DRAFT_MODEL_CHECKPOINT"] = str(checkpoint.resolve())
    metadata = get_league_meta()
    team_id = args.team_id or DEFAULT_TEAM_ID
    if team_id is None:
        raise ValueError("--team-id is required when DEFAULT_TEAM_ID is not configured")
    recommendations = get_draft_recommendations(
        metadata, team_id, PERIODS["projected"], (), 300, (), None, False, True,
    )
    report = benchmark_adaptive_vs_legacy(
        recommendations["players"],
        len(metadata.get_teams()),
        recommendations["draft_rounds"],
        categories_for_format(args.format),
        roster_slots=recommendations.get("roster_slots"),
        runs_per_slot=args.runs_per_slot,
        opponent_field=args.opponent_field,
    )
    report["_provenance"] = {
        "checkpoint": _resolved(checkpoint),
        "format": args.format,
        "learned_policy": not args.disable_learned_policy,
        "opponent_field": args.opponent_field,
        "created_at": datetime.now(timezone.utc).isoformat(),
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

    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--dataset", required=True)
    evaluate.add_argument("--checkpoint", required=True)
    evaluate.add_argument("--split", choices=("validation", "test"), default="test")
    evaluate.add_argument("--output")
    evaluate.add_argument("--execute", action="store_true")
    evaluate.set_defaults(handler=command_evaluate)

    benchmark = commands.add_parser("benchmark")
    benchmark.add_argument("--format", choices=("standard8", "custom11"), required=True)
    benchmark.add_argument("--runs-per-slot", type=int, default=20)
    benchmark.add_argument("--checkpoint", required=True)
    benchmark.add_argument("--disable-learned-policy", action="store_true")
    benchmark.add_argument("--opponent-field", choices=("mixed", "market"), default="mixed")
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
