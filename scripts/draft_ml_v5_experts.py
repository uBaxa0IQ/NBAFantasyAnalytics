"""Train and benchmark policy-only market experts. Plan-only unless --execute."""
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

DATASET = ROOT / "artifacts/draft_ml/standard8-v4/dataset.jsonl.gz"
BASE = ROOT / "artifacts/draft_ml/standard8-v4/checkpoint"
SNAPSHOT = ROOT / "artifacts/draft_ml/standard8/standard8-market-v4-inputs.json"
V4_REPORTS = ROOT / "artifacts/draft_ml/standard8-v4"
OUT = ROOT / "artifacts/draft_ml/standard8-v5-experts"
MARKETS = ("conservative", "espn_draft", "league_rater", "category_z")
FIELDS = ("human", "heuristic_mixed")
SAFE_ML_MARKETS = ("espn_draft", "category_z")
SEED = 2_609_507


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, payload):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_plan():
    required = [DATASET, BASE / "manifest.json", SNAPSHOT]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing v4 inputs: {missing}")
    base_manifest = json.loads((BASE / "manifest.json").read_text(encoding="utf-8"))
    if base_manifest.get("dataset_sha256") != sha256(DATASET):
        raise ValueError("v4 dataset/checkpoint mismatch")
    stages = []
    common = ["-m", "web.backend.services.draft_ml"]
    for index, market in enumerate(MARKETS):
        checkpoint = OUT / "checkpoints" / market
        stages.append({
            "name": f"train-{market}",
            "args": common + [
                "train-expert", "--format", "standard8", "--dataset", str(DATASET),
                "--base-checkpoint", str(BASE), "--checkpoint", str(checkpoint),
                "--market-model", market, "--seed", str(SEED + index), "--execute",
            ],
            "output": str(checkpoint / "manifest.json"),
        })
        stages.append({
            "name": f"test-{market}",
            "args": common + [
                "evaluate", "--dataset", str(DATASET), "--checkpoint", str(checkpoint),
                "--split", "test", "--market-model", market,
                "--output", str(OUT / f"test-{market}.json"), "--execute",
            ],
            "output": str(OUT / f"test-{market}.json"),
        })
        for field in FIELDS:
            report = OUT / f"benchmark-{market}-{field}.json"
            stages.append({
                "name": f"benchmark-{market}-{field}",
                "args": common + [
                    "benchmark", "--format", "standard8", "--checkpoint", str(checkpoint),
                    "--input-snapshot", str(SNAPSHOT), "--market-model", market,
                    "--opponent-field", field, "--seed", "2609407", "--runs-per-slot", "10",
                    "--output", str(report), "--execute",
                ],
                "output": str(report),
            })
    return {
        "status": "prepared_not_started",
        "operation": "policy-only market experts and safe hybrid research",
        "dataset": str(DATASET),
        "dataset_sha256": sha256(DATASET),
        "base_checkpoint": str(BASE),
        "base_manifest_sha256": sha256(BASE / "manifest.json"),
        "snapshot": str(SNAPSHOT),
        "snapshot_sha256": sha256(SNAPSHOT),
        "output_dir": str(OUT),
        "markets": list(MARKETS),
        "fields": list(FIELDS),
        "safe_ml_markets": list(SAFE_ML_MARKETS),
        "fallback_markets": sorted(set(MARKETS) - set(SAFE_ML_MARKETS)),
        "stages": stages,
        "time_estimate": {
            "training_and_tests_minutes": [3, 10],
            "benchmarks_minutes": 52,
            "total_minutes_range": [55, 90],
            "basis": "Eight reports at the measured v4 rate (~6.4 min/report); no dataset generation.",
        },
        "constraints": {
            "research_only": True,
            "auto_promote": False,
            "deployment": False,
            "test_already_inspected": True,
            "previous_season_stats_only": True,
        },
    }


def fingerprint(plan):
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8"))
    paths = [Path(__file__), DATASET, BASE / "manifest.json", SNAPSHOT]
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


def validate_output(stage):
    path = Path(stage["output"])
    if not path.is_file():
        raise ValueError(f"Missing stage output: {stage['name']}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    parts = stage["name"].split("-", 1)
    kind, market = parts
    if kind == "train":
        if payload.get("expert_market") != market or payload.get("dataset_sha256") != sha256(DATASET):
            raise ValueError(f"Invalid expert checkpoint: {market}")
        for name, expected in payload.get("artifact_sha256", {}).items():
            if sha256(path.parent / name) != expected:
                raise ValueError(f"Expert artifact checksum mismatch: {market}/{name}")
    elif kind == "test":
        provenance = payload.get("_provenance") or {}
        if provenance.get("market_model") != market or provenance.get("dataset_sha256") != sha256(DATASET):
            raise ValueError(f"Invalid expert test report: {market}")
    else:
        market, field = market.rsplit("-", 1)
        provenance = payload.get("_provenance") or {}
        if (provenance.get("market_model") != market
                or provenance.get("opponent_field") != field
                or provenance.get("seed") != 2_609_407
                or provenance.get("input_sha256") != sha256(SNAPSHOT)):
            raise ValueError(f"Invalid benchmark report: {market}/{field}")


def paired_delta(left, right):
    if len(left) != len(right):
        raise ValueError("Unpaired benchmark outcomes")
    values = [a["category_wins"] - b["category_wins"] for a, b in zip(left, right)]
    return {"delta": fmean(values), "ci95": _ci95(values), "samples": len(values)}


def summarize():
    scenarios = []
    hybrid_vs_heuristic = []
    hybrid_vs_v4 = []
    for market in MARKETS:
        manifest = json.loads((OUT / "checkpoints" / market / "manifest.json").read_text(encoding="utf-8"))
        test = json.loads((OUT / f"test-{market}.json").read_text(encoding="utf-8"))
        for field in FIELDS:
            expert = json.loads((OUT / f"benchmark-{market}-{field}.json").read_text(encoding="utf-8"))
            v4 = json.loads((V4_REPORTS / f"control-{market}-{field}-new.json").read_text(encoding="utf-8"))
            expert_outcomes = expert["paired_outcomes"]["adaptive"]
            heuristic_outcomes = expert["paired_outcomes"]["adaptive_heuristic"]
            v4_outcomes = v4["paired_outcomes"]["adaptive"]
            use_ml = market in SAFE_ML_MARKETS
            hybrid = expert_outcomes if use_ml else heuristic_outcomes
            hybrid_vs_heuristic.extend(
                a["category_wins"] - b["category_wins"]
                for a, b in zip(hybrid, heuristic_outcomes)
            )
            hybrid_vs_v4.extend(
                a["category_wins"] - b["category_wins"]
                for a, b in zip(hybrid, v4_outcomes)
            )
            scenarios.append({
                "market": market,
                "field": field,
                "safe_route": "expert" if use_ml else "adaptive_heuristic",
                "expert_vs_v4": paired_delta(expert_outcomes, v4_outcomes),
                "expert_vs_heuristic": paired_delta(expert_outcomes, heuristic_outcomes),
                "expert_validation": manifest["validation_metrics"]["reranker"],
                "v4_validation_same_market": manifest["base_validation_metrics_same_market"]["reranker"],
                "expert_test": test["reranker"],
            })
    return {
        "research_only": True,
        "manual_review_required": True,
        "auto_promote": False,
        "safe_routes_precommitted": {
            "expert": list(SAFE_ML_MARKETS),
            "adaptive_heuristic": sorted(set(MARKETS) - set(SAFE_ML_MARKETS)),
        },
        "safe_hybrid_vs_heuristic": {
            "delta": fmean(hybrid_vs_heuristic), "ci95": _ci95(hybrid_vs_heuristic),
            "samples": len(hybrid_vs_heuristic),
        },
        "safe_hybrid_vs_v4": {
            "delta": fmean(hybrid_vs_v4), "ci95": _ci95(hybrid_vs_v4),
            "samples": len(hybrid_vs_v4),
        },
        "scenarios": scenarios,
        "limitations": [
            "The v4 test split and benchmark snapshot have already been inspected.",
            "All player statistics are previous-season fallback values.",
            "These results select a v5 candidate; fresh ESPN projections require a new final holdout.",
        ],
    }


def execute(plan):
    for dependency in ("sklearn", "joblib", "numpy"):
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
            raise ValueError("Code/input changed; existing v5 journal is preserved and cannot be mixed")
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
        for number, stage in enumerate(plan["stages"], 1):
            if stage["name"] in state["completed"]:
                validate_output(stage)
                print(f"{number}/{len(plan['stages'])} SKIP {stage['name']}", flush=True)
                continue
            print(f"{number}/{len(plan['stages'])} START {stage['name']}", flush=True)
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
                            print(f"{stage['name']}: {(time.monotonic()-started)/60:.1f} min", flush=True)
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
                raise RuntimeError(f"{stage['name']} failed; see {logs / (stage['name'] + '.log')}")
            validate_output(stage)
            state["completed"].append(stage["name"])
            atomic_json(state_path, state)
            print(f"DONE {stage['name']}", flush=True)
        atomic_json(OUT / "summary.json", summarize())
        print("COMPLETE. Research reports saved; no promotion or deployment.", flush=True)


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
