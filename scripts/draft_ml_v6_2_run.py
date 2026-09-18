"""Resumable five-seed v6.2 evolution, diagnostics, and frozen ensemble evaluation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from statistics import fmean, pstdev
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.backend.services.draft_benchmark import _ci95
from web.backend.services.draft_ml.evolution import EvolutionConfig


BASE_CONFIG = ROOT / "configs/draft_ml_standard8_v6_2_pbt.json"
SNAPSHOT = ROOT / "artifacts/draft_ml/standard8/standard8-market-v4-inputs.json"
OUT = ROOT / "artifacts/draft_ml/standard8-v6-2-pbt"
TRAIN_SEEDS = (2_609_621, 2_609_622, 2_609_623, 2_609_624, 2_609_625)
MARKETS = ("conservative", "espn_draft", "league_rater", "category_z")
FIELDS = ("human", "heuristic_mixed")
DIAGNOSTIC_RUNS_PER_SLOT = 5
FINAL_RUNS_PER_SLOT = 10
DIAGNOSTIC_SEED_BASE = 2_609_700
FINAL_BENCHMARK_SEED = 2_609_999


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _seed_dir(seed):
    return OUT / f"seed-{seed}"


def _benchmark_stage(name, checkpoint, output, market, field, seed, runs, owner):
    return {
        "name": name,
        "kind": "benchmark",
        "owner": owner,
        "market": market,
        "field": field,
        "seed": seed,
        "runs_per_slot": runs,
        "checkpoint": str(checkpoint),
        "output": str(output),
        "args": [
            "-m", "web.backend.services.draft_ml", "benchmark",
            "--format", "standard8", "--checkpoint", str(checkpoint),
            "--input-snapshot", str(SNAPSHOT), "--market-model", market,
            "--opponent-field", field, "--seed", str(seed),
            "--runs-per-slot", str(runs), "--output", str(output), "--execute",
        ],
    }


def build_plan():
    for path in (BASE_CONFIG, SNAPSHOT):
        if not path.is_file():
            raise FileNotFoundError(path)
    base_payload = json.loads(BASE_CONFIG.read_text(encoding="utf-8"))
    base_config = EvolutionConfig(**base_payload).validate()
    evolution_stages = []
    diagnostic_stages = []
    for index, seed in enumerate(TRAIN_SEEDS):
        seed_root = _seed_dir(seed)
        config_path = seed_root / "config.json"
        checkpoint = seed_root / "evolution/checkpoint"
        evolution_stages.append({
            "name": f"evolve-seed-{seed}", "kind": "evolve", "seed": seed,
            "config": str(config_path), "checkpoint": str(checkpoint),
            "output": str(checkpoint / "manifest.json"),
            "args": [
                "-m", "web.backend.services.draft_ml.evolution",
                "--config", str(config_path), "--input-snapshot", str(SNAPSHOT),
                "--output-dir", str(seed_root / "evolution"), "--execute",
            ],
        })
        diagnostic_seed = DIAGNOSTIC_SEED_BASE + index * 101
        for market in MARKETS:
            for field in FIELDS:
                name = f"diagnostic-{seed}-{market}-{field}"
                diagnostic_stages.append(_benchmark_stage(
                    name, checkpoint, seed_root / f"benchmark-{market}-{field}.json",
                    market, field, diagnostic_seed, DIAGNOSTIC_RUNS_PER_SLOT,
                    f"seed-{seed}",
                ))
    stages = [*evolution_stages, *diagnostic_stages]
    ensemble_checkpoint = OUT / "ensemble/checkpoint"
    stages.append({
        "name": "build-frozen-ensemble", "kind": "ensemble",
        "output": str(ensemble_checkpoint / "manifest.json"),
        "checkpoint": str(ensemble_checkpoint),
    })
    for market in MARKETS:
        for field in FIELDS:
            stages.append(_benchmark_stage(
                f"final-ensemble-{market}-{field}", ensemble_checkpoint,
                OUT / f"ensemble/benchmark-{market}-{field}.json",
                market, field, FINAL_BENCHMARK_SEED, FINAL_RUNS_PER_SLOT,
                "ensemble",
            ))
    per_seed_training = (
        base_config.generations
        * (base_config.drafts_per_generation + base_config.validation_drafts)
        + base_config.final_drafts
    )
    return {
        "status": "prepared_not_started",
        "operation": "v6.2 five-seed multi-objective market-free evolution and ensemble",
        "base_config": base_payload,
        "base_config_path": str(BASE_CONFIG),
        "base_config_sha256": sha256(BASE_CONFIG),
        "snapshot": str(SNAPSHOT), "snapshot_sha256": sha256(SNAPSHOT),
        "output_dir": str(OUT), "training_seeds": list(TRAIN_SEEDS),
        "training_full_drafts_max_per_seed": per_seed_training,
        "training_full_drafts_max_total": per_seed_training * len(TRAIN_SEEDS),
        "diagnostic_full_drafts": (
            len(TRAIN_SEEDS) * len(MARKETS) * len(FIELDS)
            * DIAGNOSTIC_RUNS_PER_SLOT * base_config.team_count * 5
        ),
        "final_ensemble_benchmark_full_drafts": (
            len(MARKETS) * len(FIELDS) * FINAL_RUNS_PER_SLOT * base_config.team_count * 5
        ),
        "stages": stages,
        "time_estimate_hours": {"likely": [14, 20], "reserve": 24},
        "guarantees": {
            "market_features_in_training": False,
            "adp_in_training": False,
            "player_rater_in_training": False,
            "independent_training_seeds": len(TRAIN_SEEDS),
            "fixed_validation_per_seed": True,
            "multi_objective_fitness": True,
            "niche_elites": True,
            "ensemble_precommitted": True,
            "diagnostics_do_not_select_members": True,
            "final_benchmark_seed_separate": True,
            "auto_promote": False,
            "deployment": False,
            "resume_each_generation_and_stage": True,
        },
    }


def fingerprint(plan):
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8"))
    paths = [Path(__file__), BASE_CONFIG, SNAPSHOT]
    paths += sorted((ROOT / "web/backend/services/draft_ml").glob("*.py"))
    paths += sorted((ROOT / "web/backend").glob("*.py"))
    for path in paths:
        if path.is_file():
            digest.update(str(path).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


@contextmanager
def run_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def write_seed_configs(plan):
    for seed in TRAIN_SEEDS:
        payload = deepcopy(plan["base_config"])
        payload["seed"] = seed
        atomic_json(_seed_dir(seed) / "config.json", payload)


def build_ensemble(plan):
    checkpoint = OUT / "ensemble/checkpoint"
    if checkpoint.exists():
        manifest_path = checkpoint / "manifest.json"
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
    manifests, genomes = [], []
    for seed in TRAIN_SEEDS:
        source = _seed_dir(seed) / "evolution/checkpoint"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("uses_market_features") is not False:
            raise ValueError(f"Seed {seed} is not market-free")
        manifests.append(manifest)
        genome = json.loads((source / "genome.json").read_text(encoding="utf-8"))
        genome["ensemble_seed"] = seed
        genomes.append(genome)
    categories = manifests[0]["categories"]
    roster_slots = manifests[0]["roster_slots"]
    if any(row["categories"] != categories or row["roster_slots"] != roster_slots for row in manifests):
        raise ValueError("Seed checkpoints use incompatible league formats")
    checkpoint.mkdir(parents=True, exist_ok=True)
    atomic_json(checkpoint / "genomes.json", genomes)
    manifest = {
        "model_version": 6,
        "experiment_version": "6.2-ensemble",
        "policy_type": "market_free_ensemble_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "format": "standard8", "categories": categories, "roster_slots": roster_slots,
        "ensemble_method": "equal_weight_mean_normalized_rank",
        "ensemble_size": len(genomes), "training_seeds": list(TRAIN_SEEDS),
        "source_checkpoints": [str(_seed_dir(seed) / "evolution/checkpoint") for seed in TRAIN_SEEDS],
        "diagnostics_used_for_member_selection": False,
        "candidate_limit": min(row["candidate_limit"] for row in manifests),
        "inference_candidate_limit": min(row["inference_candidate_limit"] for row in manifests),
        "uses_market_features": False, "uses_adp": False, "uses_player_rater": False,
        "metadata": {
            "research_only": True,
            "projection_fallback_only": all(
                row.get("metadata", {}).get("projection_fallback_only") is True
                for row in manifests
            ),
        },
        "artifact_sha256": {"genomes.json": sha256(checkpoint / "genomes.json")},
    }
    atomic_json(checkpoint / "manifest.json", manifest)
    return manifest


def validate_stage(stage, plan):
    path = Path(stage["output"])
    if not path.is_file():
        raise ValueError(f"Missing output: {stage['name']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if stage["kind"] == "evolve":
        expected_config = deepcopy(plan["base_config"])
        expected_config["seed"] = stage["seed"]
        completed = payload.get("completed_generations")
        configured = expected_config["generations"]
        if (
            payload.get("policy_type") != "market_free_linear_v1"
            or payload.get("uses_market_features") is not False
            or payload.get("selection_scope") != "all_generation_champions_via_fixed_validation_arena"
            or payload.get("config") != expected_config
            or not isinstance(completed, int) or not 1 <= completed <= configured
            or (completed < configured and payload.get("stopped_early") is not True)
        ):
            raise ValueError(f"Invalid seed checkpoint: {stage['seed']}")
    elif stage["kind"] == "ensemble":
        if (
            payload.get("policy_type") != "market_free_ensemble_v1"
            or payload.get("training_seeds") != list(TRAIN_SEEDS)
            or payload.get("ensemble_size") != len(TRAIN_SEEDS)
            or payload.get("diagnostics_used_for_member_selection") is not False
        ):
            raise ValueError("Invalid frozen ensemble checkpoint")
    else:
        provenance = payload.get("_provenance") or {}
        if (
            provenance.get("market_model") != stage["market"]
            or provenance.get("opponent_field") != stage["field"]
            or provenance.get("seed") != stage["seed"]
            or provenance.get("input_sha256") != plan["snapshot_sha256"]
            or provenance.get("checkpoint") != str(Path(stage["checkpoint"]).resolve())
        ):
            raise ValueError(f"Invalid benchmark provenance: {stage['name']}")
    for name, expected in (payload.get("artifact_sha256") or {}).items():
        if sha256(path.parent / name) != expected:
            raise ValueError(f"Artifact checksum mismatch: {stage['name']}/{name}")


def _comparison(report):
    learned = report["paired_outcomes"]["adaptive"]
    heuristic = report["paired_outcomes"]["adaptive_heuristic"]
    category = [a["category_wins"] - b["category_wins"] for a, b in zip(learned, heuristic)]
    rank = [b["league_rank"] - a["league_rank"] for a, b in zip(learned, heuristic)]
    top_four = [float(a["league_rank"] <= 4) - float(b["league_rank"] <= 4) for a, b in zip(learned, heuristic)]
    return category, rank, top_four


def _metrics(values):
    return {"delta": fmean(values), "ci95": _ci95(values), "samples": len(values)}


def summarize(plan):
    models = {}
    for owner in [*(f"seed-{seed}" for seed in TRAIN_SEEDS), "ensemble"]:
        category, rank, top_four, scenarios = [], [], [], []
        root = OUT / "ensemble" if owner == "ensemble" else OUT / owner
        for market in MARKETS:
            for field in FIELDS:
                report = json.loads((root / f"benchmark-{market}-{field}.json").read_text(encoding="utf-8"))
                c_values, r_values, t_values = _comparison(report)
                category += c_values
                rank += r_values
                top_four += t_values
                scenarios.append({
                    "market": market, "field": field,
                    "category_wins": _metrics(c_values),
                    "league_rank_improvement": _metrics(r_values),
                    "top_four_rate_delta": _metrics(t_values),
                })
        models[owner] = {
            "aggregate": {
                "category_wins": _metrics(category),
                "league_rank_improvement": _metrics(rank),
                "top_four_rate_delta": _metrics(top_four),
            },
            "scenarios": scenarios,
        }
    seed_deltas = [models[f"seed-{seed}"]["aggregate"]["category_wins"]["delta"] for seed in TRAIN_SEEDS]
    return {
        "research_only": True, "manual_review_required": True, "auto_promote": False,
        "training_market_free": True,
        "seed_robustness": {
            "category_delta_mean": fmean(seed_deltas),
            "category_delta_stddev": pstdev(seed_deltas),
            "category_delta_min": min(seed_deltas),
            "all_seeds_positive": all(value > 0 for value in seed_deltas),
        },
        "models": models,
        "ensemble_checkpoint": str(OUT / "ensemble/checkpoint"),
        "limitations": [
            "The frozen snapshot contains previous-season fallback player statistics.",
            "Market scenarios are external stress tests and are not policy inputs.",
            "Fresh 2027 projections and a new untouched holdout are required for a final claim.",
        ],
    }


def _run_subprocess(stage, log_path, env, plan):
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, *stage["args"]], cwd=ROOT, env=env,
            stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    detail = ""
                    if stage["kind"] == "evolve":
                        state_path = _seed_dir(stage["seed"]) / "evolution/evolution-state.json"
                        if state_path.exists():
                            try:
                                done = json.loads(state_path.read_text(encoding="utf-8"))["completed_generations"]
                                detail = f" | generations {done}/{plan['base_config']['generations']}"
                            except (OSError, ValueError, KeyError):
                                pass
                    print(f"{stage['name']}: {(time.monotonic() - started) / 60:.1f} min{detail}", flush=True)
        except BaseException:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                else:
                    process.terminate()
                process.wait()
            raise
    if code != 0:
        raise RuntimeError(f"{stage['name']} failed; log: {log_path}")


def execute(plan):
    for dependency in ("numpy", "sklearn", "joblib"):
        if importlib.util.find_spec(dependency) is None:
            raise RuntimeError(f"Missing dependency: {dependency}")
    OUT.mkdir(parents=True, exist_ok=True)
    with run_lock(OUT / "run.lock"):
        digest = fingerprint(plan)
        state_path = OUT / "run-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
            "fingerprint": digest, "completed": [],
        }
        if state.get("fingerprint") != digest:
            raise ValueError("Code/config/input changed; existing v6.2 run is preserved")
        write_seed_configs(plan)
        atomic_json(state_path, state)
        atomic_json(OUT / "plan.json", plan)
        logs = OUT / ("logs-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        logs.mkdir()
        env = dict(os.environ)
        env.update({key: "1" for key in (
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "PYTHONUNBUFFERED", "DRAFT_ML_STRICT",
        )})
        env.pop("DRAFT_DISABLE_LEARNED", None)
        env.pop("DRAFT_MODEL_CHECKPOINT", None)
        for index, stage in enumerate(plan["stages"], 1):
            if stage["name"] in state["completed"]:
                validate_stage(stage, plan)
                print(f"{index}/{len(plan['stages'])} SKIP {stage['name']}", flush=True)
                continue
            print(f"{index}/{len(plan['stages'])} START {stage['name']}", flush=True)
            if stage["kind"] == "ensemble":
                build_ensemble(plan)
            else:
                _run_subprocess(stage, logs / f"{stage['name']}.log", env, plan)
            validate_stage(stage, plan)
            state["completed"].append(stage["name"])
            atomic_json(state_path, state)
            print(f"DONE {stage['name']}", flush=True)
        atomic_json(OUT / "summary.json", summarize(plan))
        print("COMPLETE. Research only; no promotion or deployment.", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    plan = build_plan()
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    execute(plan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
