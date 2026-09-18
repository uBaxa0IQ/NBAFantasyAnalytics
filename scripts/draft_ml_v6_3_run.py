"""Final linear-policy phase: common meta-validation, cross-play, weighted ensemble, holdout."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from statistics import fmean, pstdev
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.backend.services.draft_benchmark import _ci95
from web.backend.services.draft_ml.evolution import (
    EvolutionConfig, _tournament_metrics, fixed_anchor_population,
)


SOURCE = ROOT / "artifacts/draft_ml/standard8-v6-2-pbt"
SNAPSHOT = ROOT / "artifacts/draft_ml/standard8/standard8-market-v4-inputs.json"
OUT = ROOT / "artifacts/draft_ml/standard8-v6-3-meta"
SEEDS = (2_609_621, 2_609_622, 2_609_623, 2_609_624, 2_609_625)
MARKETS = ("conservative", "espn_draft", "league_rater", "category_z")
FIELDS = ("human", "heuristic_mixed")
PREFILTER_PER_SEED = 8
META_DRAFTS_PER_CANDIDATE = 80
CROSSPLAY_CANDIDATES = 24
CROSSPLAY_DRAFTS = 1_600
ENSEMBLE_SIZE = 7
MAX_MEMBERS_PER_SEED = 2
META_SEED = 2_610_201
META_SCHEDULE = 210_201
CROSSPLAY_SCHEDULE = 210_301
FINAL_HOLDOUT_SEED = 2_610_777
FINAL_RUNS_PER_SLOT = 10


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _source_state(seed):
    return SOURCE / f"seed-{seed}/evolution/evolution-state.json"


def _source_checkpoint(seed):
    return SOURCE / f"seed-{seed}/evolution/checkpoint"


def _load_snapshot():
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return payload["players"], tuple(payload["categories"]), tuple(payload["roster_slots"])


def _common_config():
    manifest = json.loads((_source_checkpoint(SEEDS[0]) / "manifest.json").read_text(encoding="utf-8"))
    payload = deepcopy(manifest["config"])
    payload.update({
        "seed": META_SEED,
        "hall_slots_per_draft": 0,
        "anchor_slots_per_draft": 9,
        "workers": 8,
    })
    return EvolutionConfig(**payload).validate()


def _candidate_pool():
    candidates = []
    for seed in SEEDS:
        state = json.loads(_source_state(seed).read_text(encoding="utf-8"))
        archive = sorted(
            state["champion_archive"],
            key=lambda row: row["validation_metrics"]["robust_fitness"],
            reverse=True,
        )[:PREFILTER_PER_SEED]
        for row in archive:
            genome = deepcopy(row)
            source_id = genome["id"]
            genome["id"] = f"meta-{seed}-{source_id}"
            genome["source_seed"] = seed
            genome["source_policy_id"] = source_id
            candidates.append(genome)
    return candidates


def _benchmark_stage(owner, checkpoint, market, field):
    root = OUT / owner
    output = root / f"benchmark-{market}-{field}.json"
    return {
        "name": f"holdout-{owner}-{market}-{field}", "kind": "benchmark",
        "owner": owner, "checkpoint": str(checkpoint), "market": market, "field": field,
        "seed": FINAL_HOLDOUT_SEED, "output": str(output),
        "args": [
            "-m", "web.backend.services.draft_ml", "benchmark",
            "--format", "standard8", "--checkpoint", str(checkpoint),
            "--input-snapshot", str(SNAPSHOT), "--market-model", market,
            "--opponent-field", field, "--seed", str(FINAL_HOLDOUT_SEED),
            "--runs-per-slot", str(FINAL_RUNS_PER_SLOT),
            "--output", str(output), "--execute",
        ],
    }


def build_plan():
    required = [SNAPSHOT, SOURCE / "summary.json", SOURCE / "ensemble/checkpoint/manifest.json"]
    required += [_source_state(seed) for seed in SEEDS]
    required += [_source_checkpoint(seed) / "manifest.json" for seed in SEEDS]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    source_hashes = {str(path): sha256(path) for path in required}
    stages = [
        {"name": "common-meta-validation", "kind": "meta", "output": str(OUT / "meta-validation.json")},
        {"name": "champion-cross-play", "kind": "crossplay", "output": str(OUT / "cross-play.json")},
        {"name": "build-weighted-ensemble", "kind": "ensemble", "output": str(OUT / "ensemble/checkpoint/manifest.json")},
    ]
    checkpoints = {
        "v63": OUT / "ensemble/checkpoint",
        "v62-control": SOURCE / "ensemble/checkpoint",
    }
    for owner, checkpoint in checkpoints.items():
        for market in MARKETS:
            for field in FIELDS:
                stages.append(_benchmark_stage(owner, checkpoint, market, field))
    return {
        "status": "prepared_not_started",
        "operation": "v6.3 common meta-validation, cross-play, weighted ensemble and untouched-seed holdout",
        "source": str(SOURCE), "source_hashes": source_hashes,
        "snapshot": str(SNAPSHOT), "snapshot_sha256": sha256(SNAPSHOT),
        "output_dir": str(OUT), "source_seeds": list(SEEDS),
        "candidate_pool": len(SEEDS) * PREFILTER_PER_SEED,
        "meta_validation_full_drafts": len(SEEDS) * PREFILTER_PER_SEED * META_DRAFTS_PER_CANDIDATE,
        "crossplay_full_drafts": CROSSPLAY_DRAFTS,
        "holdout_full_drafts": len(checkpoints) * len(MARKETS) * len(FIELDS) * FINAL_RUNS_PER_SLOT * 10 * 5,
        "stages": stages,
        "time_estimate_hours": {"likely": [8, 13], "reserve": 15},
        "guarantees": {
            "no_new_training": True,
            "all_source_seeds_considered": True,
            "common_meta_arena": True,
            "cross_play": True,
            "ensemble_frozen_before_holdout": True,
            "final_holdout_seed_unused": True,
            "v62_control_same_holdout": True,
            "market_features_in_policy": False,
            "auto_promote": False,
            "deployment": False,
            "resume_meta_candidate_and_stage": True,
        },
    }


def fingerprint(plan):
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8"))
    paths = [Path(__file__), SNAPSHOT]
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


def run_meta_validation(plan):
    players, categories, slots = _load_snapshot()
    config = _common_config()
    anchors = fixed_anchor_population(categories, config)
    candidates = _candidate_pool()
    state_path = OUT / "meta-validation-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "fingerprint": fingerprint(plan), "completed": {},
    }
    if state.get("fingerprint") != fingerprint(plan):
        raise ValueError("Meta-validation inputs changed; existing state is preserved")
    for index, candidate in enumerate(candidates, 1):
        if candidate["id"] in state["completed"]:
            continue
        metrics = _tournament_metrics(
            players, categories, slots, [candidate], [], config,
            META_SCHEDULE, META_DRAFTS_PER_CANDIDATE, anchors,
        )[candidate["id"]]
        state["completed"][candidate["id"]] = metrics
        atomic_json(state_path, state)
        print(
            f"meta candidate {index}/{len(candidates)} | {candidate['id']} | "
            f"fitness {metrics['robust_fitness']:.4f}", flush=True,
        )
    atomic_json(OUT / "meta-validation.json", {
        "fingerprint": state["fingerprint"], "config": vars(config),
        "candidate_count": len(candidates), "drafts_per_candidate": META_DRAFTS_PER_CANDIDATE,
        "candidates": candidates, "metrics": state["completed"],
    })


def _crossplay_pool(meta):
    candidates = meta["candidates"]
    metrics = meta["metrics"]
    by_seed = {}
    for seed in SEEDS:
        rows = [row for row in candidates if row["source_seed"] == seed]
        by_seed[seed] = sorted(rows, key=lambda row: metrics[row["id"]]["robust_fitness"], reverse=True)
    selected = [row for seed in SEEDS for row in by_seed[seed][:3]]
    selected_ids = {row["id"] for row in selected}
    ranked = sorted(candidates, key=lambda row: metrics[row["id"]]["robust_fitness"], reverse=True)
    for row in ranked:
        if row["id"] not in selected_ids:
            selected.append(row)
            selected_ids.add(row["id"])
        if len(selected) >= CROSSPLAY_CANDIDATES:
            break
    return selected


def run_crossplay():
    players, categories, slots = _load_snapshot()
    meta = json.loads((OUT / "meta-validation.json").read_text(encoding="utf-8"))
    candidates = _crossplay_pool(meta)
    config = _common_config()
    config = EvolutionConfig(**{
        **vars(config), "hall_slots_per_draft": 0, "anchor_slots_per_draft": 3,
    }).validate()
    anchors = fixed_anchor_population(categories, config)
    metrics = _tournament_metrics(
        players, categories, slots, candidates, [], config,
        CROSSPLAY_SCHEDULE, CROSSPLAY_DRAFTS, anchors,
    )
    atomic_json(OUT / "cross-play.json", {
        "config": vars(config), "drafts": CROSSPLAY_DRAFTS,
        "candidate_ids": [row["id"] for row in candidates], "metrics": metrics,
    })


def _zscore_map(values):
    mean = fmean(values.values())
    scale = pstdev(values.values()) or 1.0
    return {key: (value - mean) / scale for key, value in values.items()}


def _select_members(meta, crossplay):
    candidates = {row["id"]: row for row in meta["candidates"]}
    eligible = crossplay["candidate_ids"]
    meta_values = {identity: meta["metrics"][identity]["robust_fitness"] for identity in eligible}
    cross_values = {identity: crossplay["metrics"][identity]["robust_fitness"] for identity in eligible}
    meta_z, cross_z = _zscore_map(meta_values), _zscore_map(cross_values)
    combined = {identity: 0.45 * meta_z[identity] + 0.55 * cross_z[identity] for identity in eligible}
    ranked = sorted(eligible, key=lambda identity: combined[identity], reverse=True)
    selected, counts = [], {seed: 0 for seed in SEEDS}
    for identity in ranked:
        seed = candidates[identity]["source_seed"]
        if counts[seed] >= MAX_MEMBERS_PER_SEED:
            continue
        selected.append(identity)
        counts[seed] += 1
        if len(selected) == ENSEMBLE_SIZE:
            break
    represented = {candidates[identity]["source_seed"] for identity in selected}
    if len(represented) < 3:
        raise RuntimeError("Meta-selection produced fewer than three independent seeds")
    maximum = max(combined[identity] for identity in selected)
    raw_weights = {identity: math.exp((combined[identity] - maximum) / 0.75) for identity in selected}
    total = sum(raw_weights.values())
    members = []
    for identity in selected:
        genome = deepcopy(candidates[identity])
        genome.pop("validation_metrics", None)
        genome["ensemble_weight"] = raw_weights[identity] / total
        genome["meta_fitness"] = meta_values[identity]
        genome["crossplay_fitness"] = cross_values[identity]
        genome["combined_selection_score"] = combined[identity]
        members.append(genome)
    return members, combined


def build_ensemble():
    checkpoint = OUT / "ensemble/checkpoint"
    manifest_path = checkpoint / "manifest.json"
    if manifest_path.exists():
        return
    meta = json.loads((OUT / "meta-validation.json").read_text(encoding="utf-8"))
    crossplay = json.loads((OUT / "cross-play.json").read_text(encoding="utf-8"))
    members, _ = _select_members(meta, crossplay)
    source_manifest = json.loads((_source_checkpoint(SEEDS[0]) / "manifest.json").read_text(encoding="utf-8"))
    checkpoint.mkdir(parents=True, exist_ok=True)
    atomic_json(checkpoint / "genomes.json", members)
    manifest = {
        "model_version": 6, "experiment_version": "6.3-meta-ensemble",
        "policy_type": "market_free_ensemble_v1",
        "created_at": datetime.now(timezone.utc).isoformat(), "format": "standard8",
        "categories": source_manifest["categories"], "roster_slots": source_manifest["roster_slots"],
        "ensemble_method": "meta_crossplay_softmax_weighted_normalized_rank",
        "ensemble_size": len(members),
        "member_source_seeds": [row["source_seed"] for row in members],
        "member_source_policy_ids": [row["source_policy_id"] for row in members],
        "member_weights": [row["ensemble_weight"] for row in members],
        "selection_used_final_holdout": False,
        "meta_seed": META_SEED, "crossplay_schedule": CROSSPLAY_SCHEDULE,
        "candidate_limit": source_manifest["candidate_limit"],
        "inference_candidate_limit": source_manifest["inference_candidate_limit"],
        "uses_market_features": False, "uses_adp": False, "uses_player_rater": False,
        "metadata": {"research_only": True, "projection_fallback_only": True},
        "artifact_sha256": {"genomes.json": sha256(checkpoint / "genomes.json")},
    }
    atomic_json(manifest_path, manifest)


def validate_stage(stage, plan):
    path = Path(stage["output"])
    if not path.is_file():
        raise ValueError(f"Missing output: {stage['name']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if stage["kind"] == "meta":
        if payload.get("candidate_count") != len(SEEDS) * PREFILTER_PER_SEED:
            raise ValueError("Incomplete common meta-validation")
    elif stage["kind"] == "crossplay":
        if len(payload.get("candidate_ids", [])) != CROSSPLAY_CANDIDATES:
            raise ValueError("Incomplete champion cross-play")
    elif stage["kind"] == "ensemble":
        if (
            payload.get("policy_type") != "market_free_ensemble_v1"
            or payload.get("ensemble_size") != ENSEMBLE_SIZE
            or payload.get("selection_used_final_holdout") is not False
        ):
            raise ValueError("Invalid V6.3 ensemble")
    else:
        provenance = payload.get("_provenance") or {}
        if (
            provenance.get("market_model") != stage["market"]
            or provenance.get("opponent_field") != stage["field"]
            or provenance.get("seed") != FINAL_HOLDOUT_SEED
            or provenance.get("input_sha256") != plan["snapshot_sha256"]
            or provenance.get("checkpoint") != str(Path(stage["checkpoint"]).resolve())
        ):
            raise ValueError(f"Invalid holdout provenance: {stage['name']}")
    for name, expected in (payload.get("artifact_sha256") or {}).items():
        if sha256(path.parent / name) != expected:
            raise ValueError(f"Artifact checksum mismatch: {stage['name']}/{name}")


def _comparison(left, right):
    category = [a["category_wins"] - b["category_wins"] for a, b in zip(left, right)]
    rank = [b["league_rank"] - a["league_rank"] for a, b in zip(left, right)]
    top4 = [float(a["league_rank"] <= 4) - float(b["league_rank"] <= 4) for a, b in zip(left, right)]
    return {"category_wins": _metric(category), "league_rank_improvement": _metric(rank), "top_four_delta": _metric(top4)}


def _metric(values):
    return {"delta": fmean(values), "ci95": _ci95(values), "samples": len(values)}


def summarize():
    aggregates = {"v63_vs_heuristic": [[], [], []], "v62_vs_heuristic": [[], [], []], "v63_vs_v62": [[], [], []]}
    scenarios = []
    for market in MARKETS:
        for field in FIELDS:
            new = json.loads((OUT / f"v63/benchmark-{market}-{field}.json").read_text(encoding="utf-8"))
            old = json.loads((OUT / f"v62-control/benchmark-{market}-{field}.json").read_text(encoding="utf-8"))
            n = new["paired_outcomes"]["adaptive"]
            h = new["paired_outcomes"]["adaptive_heuristic"]
            o = old["paired_outcomes"]["adaptive"]
            comparisons = {
                "v63_vs_heuristic": _comparison(n, h),
                "v62_vs_heuristic": _comparison(o, h),
                "v63_vs_v62": _comparison(n, o),
            }
            for name, left, right in (("v63_vs_heuristic", n, h), ("v62_vs_heuristic", o, h), ("v63_vs_v62", n, o)):
                aggregates[name][0] += [a["category_wins"] - b["category_wins"] for a, b in zip(left, right)]
                aggregates[name][1] += [b["league_rank"] - a["league_rank"] for a, b in zip(left, right)]
                aggregates[name][2] += [float(a["league_rank"] <= 4) - float(b["league_rank"] <= 4) for a, b in zip(left, right)]
            scenarios.append({"market": market, "field": field, **comparisons})
    aggregate = {
        name: {
            "category_wins": _metric(values[0]),
            "league_rank_improvement": _metric(values[1]),
            "top_four_delta": _metric(values[2]),
        }
        for name, values in aggregates.items()
    }
    manifest = json.loads((OUT / "ensemble/checkpoint/manifest.json").read_text(encoding="utf-8"))
    return {
        "research_only": True, "manual_review_required": True, "auto_promote": False,
        "aggregate": aggregate, "scenarios": scenarios,
        "ensemble": {
            "checkpoint": str(OUT / "ensemble/checkpoint"),
            "member_source_seeds": manifest["member_source_seeds"],
            "member_source_policy_ids": manifest["member_source_policy_ids"],
            "member_weights": manifest["member_weights"],
        },
        "limitations": [
            "The player snapshot still uses previous-season fallback statistics.",
            "The final holdout seed is new, but the underlying player snapshot is not.",
            "Fresh 2027 projections require retraining and a genuinely new holdout.",
        ],
    }


def _run_subprocess(stage, log_path, env):
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen([sys.executable, *stage["args"]], cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    print(f"{stage['name']}: {(time.monotonic() - started) / 60:.1f} min", flush=True)
        except BaseException:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"fingerprint": digest, "completed": []}
        if state.get("fingerprint") != digest:
            raise ValueError("Code/input changed; existing V6.3 state is preserved")
        atomic_json(state_path, state)
        atomic_json(OUT / "plan.json", plan)
        logs = OUT / ("logs-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        logs.mkdir()
        env = dict(os.environ)
        env.update({key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "PYTHONUNBUFFERED", "DRAFT_ML_STRICT")})
        env.pop("DRAFT_DISABLE_LEARNED", None)
        env.pop("DRAFT_MODEL_CHECKPOINT", None)
        actions = {"meta": lambda: run_meta_validation(plan), "crossplay": run_crossplay, "ensemble": build_ensemble}
        for index, stage in enumerate(plan["stages"], 1):
            if stage["name"] in state["completed"]:
                validate_stage(stage, plan)
                print(f"{index}/{len(plan['stages'])} SKIP {stage['name']}", flush=True)
                continue
            print(f"{index}/{len(plan['stages'])} START {stage['name']}", flush=True)
            if stage["kind"] == "benchmark":
                _run_subprocess(stage, logs / f"{stage['name']}.log", env)
            else:
                actions[stage["kind"]]()
            validate_stage(stage, plan)
            state["completed"].append(stage["name"])
            atomic_json(state_path, state)
            print(f"DONE {stage['name']}", flush=True)
        atomic_json(OUT / "summary.json", summarize())
        print("COMPLETE. Final linear research checkpoint; no promotion/deployment.", flush=True)


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
