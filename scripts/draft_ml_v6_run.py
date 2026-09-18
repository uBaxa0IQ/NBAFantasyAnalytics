"""Resumable v6.1 market-free PBT run. Plan-only unless --execute."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from statistics import fmean
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.backend.services.draft_benchmark import _ci95
from web.backend.services.draft_ml.evolution import EvolutionConfig

CONFIG = ROOT / "configs/draft_ml_standard8_v6_pbt.json"
SNAPSHOT = ROOT / "artifacts/draft_ml/standard8/standard8-market-v4-inputs.json"
V4 = ROOT / "artifacts/draft_ml/standard8-v4"
OUT = ROOT / "artifacts/draft_ml/standard8-v6-1-pbt"
MARKETS = ("conservative", "espn_draft", "league_rater", "category_z")
FIELDS = ("human", "heuristic_mixed")
BENCHMARK_SEED = 2_609_407


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_plan():
    for path in (CONFIG, SNAPSHOT, V4 / "checkpoint/manifest.json"):
        if not path.is_file():
            raise FileNotFoundError(path)
    config = EvolutionConfig(**json.loads(CONFIG.read_text(encoding="utf-8"))).validate()
    checkpoint = OUT / "evolution/checkpoint"
    stages = [{
        "name": "evolve",
        "args": [
            "-m", "web.backend.services.draft_ml.evolution",
            "--config", str(CONFIG), "--input-snapshot", str(SNAPSHOT),
            "--output-dir", str(OUT / "evolution"), "--execute",
        ],
        "output": str(checkpoint / "manifest.json"),
    }]
    for market in MARKETS:
        for field in FIELDS:
            report = OUT / f"benchmark-{market}-{field}.json"
            stages.append({
                "name": f"benchmark-{market}-{field}",
                "args": [
                    "-m", "web.backend.services.draft_ml", "benchmark",
                    "--format", "standard8", "--checkpoint", str(checkpoint),
                    "--input-snapshot", str(SNAPSHOT), "--market-model", market,
                    "--opponent-field", field, "--seed", str(BENCHMARK_SEED),
                    "--runs-per-slot", "10", "--output", str(report), "--execute",
                ],
                "output": str(report),
            })
    return {
        "status": "prepared_not_started",
        "operation": "v6.1 market-free population self-play with fixed validation plus external stress tests",
        "config": as_json(config),
        "config_path": str(CONFIG), "config_sha256": sha256(CONFIG),
        "snapshot": str(SNAPSHOT), "snapshot_sha256": sha256(SNAPSHOT),
        "output_dir": str(OUT), "checkpoint": str(checkpoint),
        "training_full_drafts_max": (
            config.generations * (config.drafts_per_generation + config.validation_drafts)
            + config.final_drafts
        ),
        "training_full_drafts_min_with_early_stop": (
            config.early_stopping_min_generations
            * (config.drafts_per_generation + config.validation_drafts)
            + config.final_drafts
        ),
        "benchmark_full_drafts": len(MARKETS) * len(FIELDS) * 10 * config.team_count * 5,
        "stages": stages,
        "time_estimate": {
            "evolution_hours": [3.5, 6.0],
            "benchmarks_hours": [0.9, 1.8],
            "total_hours": [4.5, 8.0],
            "reserve_hours": 9.0,
            "caveat": "Estimated from the completed v6 run; fixed validation adds a second tournament per generation.",
        },
        "guarantees": {
            "market_features_in_training": False,
            "adp_in_training": False,
            "player_rater_in_training": False,
            "auto_promote": False,
            "deployment": False,
            "resume_each_generation": True,
            "early_stopping": True,
            "fixed_validation_arena": True,
            "all_generation_champions_considered": True,
            "market_free_anchor_opponents": True,
        },
    }


def as_json(config):
    from dataclasses import asdict
    return asdict(config)


def fingerprint(plan):
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8"))
    paths = [Path(__file__), CONFIG, SNAPSHOT]
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


def validate_stage(stage, plan):
    path = Path(stage["output"])
    if not path.is_file():
        raise ValueError(f"Missing output: {stage['name']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if stage["name"] == "evolve":
        completed = payload.get("completed_generations")
        configured = plan["config"]["generations"]
        valid_completion = (
            isinstance(completed, int)
            and 1 <= completed <= configured
            and (completed == configured or payload.get("stopped_early") is True)
        )
        if (payload.get("policy_type") != "market_free_linear_v1"
                or payload.get("uses_market_features") is not False
                or payload.get("selection_scope") != "all_generation_champions_via_fixed_validation_arena"
                or not valid_completion):
            raise ValueError("Invalid v6 checkpoint")
        for name, expected in payload.get("artifact_sha256", {}).items():
            if sha256(path.parent / name) != expected:
                raise ValueError(f"v6 artifact checksum mismatch: {name}")
    else:
        _, market, field = stage["name"].split("-", 2)
        provenance = payload.get("_provenance") or {}
        if (provenance.get("market_model") != market
                or provenance.get("opponent_field") != field
                or provenance.get("seed") != BENCHMARK_SEED
                or provenance.get("input_sha256") != plan["snapshot_sha256"]
                or provenance.get("checkpoint") != str(Path(plan["checkpoint"]).resolve())):
            raise ValueError(f"Invalid v6 benchmark: {market}/{field}")


def paired(left, right):
    if len(left) != len(right):
        raise ValueError("Unpaired outcomes")
    values = [a["category_wins"] - b["category_wins"] for a, b in zip(left, right)]
    return {"delta": fmean(values), "ci95": _ci95(values), "samples": len(values)}


def summarize(plan):
    rows, all_heuristic, all_v4, all_v3 = [], [], [], []
    for market in MARKETS:
        for field in FIELDS:
            report = json.loads((OUT / f"benchmark-{market}-{field}.json").read_text(encoding="utf-8"))
            v4 = json.loads((V4 / f"control-{market}-{field}-new.json").read_text(encoding="utf-8"))
            v3 = json.loads((V4 / f"control-{market}-{field}-previous.json").read_text(encoding="utf-8"))
            champion = report["paired_outcomes"]["adaptive"]
            heuristic = report["paired_outcomes"]["adaptive_heuristic"]
            old4 = v4["paired_outcomes"]["adaptive"]
            old3 = v3["paired_outcomes"]["adaptive"]
            all_heuristic += [a["category_wins"] - b["category_wins"] for a, b in zip(champion, heuristic)]
            all_v4 += [a["category_wins"] - b["category_wins"] for a, b in zip(champion, old4)]
            all_v3 += [a["category_wins"] - b["category_wins"] for a, b in zip(champion, old3)]
            rows.append({
                "market_stress_test": market, "opponent_field": field,
                "v6_vs_heuristic": paired(champion, heuristic),
                "v6_vs_v4": paired(champion, old4),
                "v6_vs_v3": paired(champion, old3),
            })
    def aggregate(values):
        return {"delta": fmean(values), "ci95": _ci95(values), "samples": len(values)}
    return {
        "research_only": True, "manual_review_required": True, "auto_promote": False,
        "training_market_free": True,
        "aggregate": {
            "v6_vs_heuristic": aggregate(all_heuristic),
            "v6_vs_v4": aggregate(all_v4),
            "v6_vs_v3": aggregate(all_v3),
        },
        "scenarios": rows,
        "checkpoint": plan["checkpoint"],
        "limitations": [
            "External market scenarios are stress tests only and were not policy inputs.",
            "Player statistics are previous-season fallback values.",
            "The benchmark snapshot has already been inspected; fresh projections are required for promotion.",
        ],
    }


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
            raise ValueError("Code/config/input changed; existing v6 run is preserved")
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
            started = time.monotonic()
            with (logs / f"{stage['name']}.log").open("w", encoding="utf-8") as output:
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
                            evolution_state = OUT / "evolution/evolution-state.json"
                            if stage["name"] == "evolve" and evolution_state.exists():
                                try:
                                    done = json.loads(evolution_state.read_text(encoding="utf-8"))["completed_generations"]
                                    detail = f" | generations {done}/{plan['config']['generations']}"
                                except (OSError, ValueError, KeyError):
                                    pass
                            print(f"{stage['name']}: {(time.monotonic()-started)/60:.1f} min{detail}", flush=True)
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
                raise RuntimeError(f"{stage['name']} failed; log: {logs / (stage['name'] + '.log')}")
            validate_stage(stage, plan)
            state["completed"].append(stage["name"])
            atomic_json(state_path, state)
            print(f"DONE {stage['name']}", flush=True)
        atomic_json(OUT / "summary.json", summarize(plan))
        print("COMPLETE. No promotion/deployment; manual review required.", flush=True)


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
