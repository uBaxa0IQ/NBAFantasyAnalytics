"""Resume-safe, paired audit of a fixed four-category punt from seat five."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts.run_v74_resilient import resilient_json as save
from web.backend.services import draft_benchmark as benchmark

CONFIG = ROOT / "configs/draft_fixed4_seat5_audit.json"
PLAYERS = None
SETTINGS = None
PROFILES = None


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def strategies(config):
    board = config["user_board"]
    punts = tuple(config["punt_categories"])
    return (
        {"id": "user_board", "policy": "board", "punts": punts, "targets": board},
        {"id": "first_three", "policy": "board", "punts": punts, "targets": board[:3]},
        {"id": "first_two", "policy": "board", "punts": punts, "targets": board[:2]},
        {"id": "adaptive_four", "policy": "adaptive_heuristic", "punts": punts},
        {"id": "giannis_open", "policy": "board", "punts": punts,
         "targets": ["Giannis Antetokounmpo", "Josh Giddey"]},
        {"id": "johnson_open", "policy": "board", "punts": punts,
         "targets": ["Jalen Johnson", "Josh Giddey"]},
    )


def fingerprint(config):
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for path in (CONFIG, Path(__file__), Path(benchmark.__file__),
                 ROOT / "web/backend/services/draft_simulation.py",
                 ROOT / "web/backend/services/draft_evaluation.py",
                 ROOT / config["snapshot"]):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize(config):
    global PLAYERS, SETTINGS, PROFILES
    SETTINGS = config
    snapshot = json.loads((ROOT / config["snapshot"]).read_text(encoding="utf-8"))
    if snapshot.get("stats_source") != "selected_period" or snapshot.get("season") != 2027:
        raise ValueError("Expected strict 2027 ESPN projections")
    if len(config["user_board"]) != config["rounds"] or len(set(config["user_board"])) != config["rounds"]:
        raise ValueError("Board must have one unique target per round")
    PLAYERS = benchmark.prepare_benchmark_market(snapshot["players"], config["categories"], "espn_draft")
    missing = set(config["user_board"]) - {row["name"] for row in PLAYERS}
    if missing:
        raise ValueError(f"Targets missing from snapshot: {sorted(missing)}")
    PROFILES = benchmark._population_profiles(config["team_count"], config["categories"], "human")


def evaluate_run(run):
    config = SETTINGS
    market, opponent_rank = benchmark._scenario(PLAYERS, config["seed"], run)
    results = {}
    for strategy in strategies(config):
        outcome = benchmark._draft_once(
            PLAYERS, config["hero_seat"], config["team_count"], config["rounds"],
            strategy, market, opponent_rank, config["slots"], config["categories"],
            include_roster=True, opponent_profiles=PROFILES,
            evaluation_noise_seed=f"fixed4-seat5:{config['seed']}:{run}",
        )
        names = [row["name"] for row in outcome.pop("roster")]
        results[strategy["id"]] = {
            "outcome": outcome,
            "roster_names": names,
            "target_hits": [names[index] == target
                            for index, target in enumerate(strategy.get("targets", ()))],
        }
    return {"run": run, "strategies": results}


def interval(values):
    array = np.asarray(values, dtype=np.float64)
    mean = float(array.mean())
    se = float(array.std(ddof=1) / np.sqrt(len(array))) if len(array) > 1 else 0.0
    return {"n": len(array), "mean": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se]}


def summarize(rows, config):
    ids = [strategy["id"] for strategy in strategies(config)]
    metrics = ("matchup_win_rate", "decisive_matchup_win_rate", "average_matchup_margin",
               "average_matchup_score", "category_wins")
    by_strategy = {}
    for strategy in strategies(config):
        strategy_id = strategy["id"]
        outcomes = [row["strategies"][strategy_id]["outcome"] for row in rows]
        common = Counter(name for row in rows for name in row["strategies"][strategy_id]["roster_names"])
        summary = {
            "metrics": {metric: interval([outcome[metric] for outcome in outcomes]) for metric in metrics},
            "category_win_rates": {category: interval([
                outcome["category_win_rate"][category] for outcome in outcomes])
                for category in config["categories"]},
            "common_players": [{"name": name, "draft_rate": count / len(rows)}
                               for name, count in common.most_common(20)],
        }
        if strategy.get("targets"):
            summary["target_hit_rates"] = [
                {"pick": pick, "name": name, "rate": float(np.mean([
                    row["strategies"][strategy_id]["target_hits"][pick - 1]
                    for row in rows]))}
                for pick, name in enumerate(strategy["targets"], 1)]
        by_strategy[strategy_id] = summary
    comparisons = {}
    for strategy_id in ids:
        if strategy_id == "user_board":
            continue
        comparisons[strategy_id] = {metric: interval([
            row["strategies"][strategy_id]["outcome"][metric]
            - row["strategies"]["user_board"]["outcome"][metric]
            for row in rows]) for metric in metrics}
    return {
        "status": "COMPLETE_EXPLORATORY_NOT_REAL_DRAFT_PROOF",
        "runs": len(rows), "seat": config["hero_seat"], "rounds": config["rounds"],
        "punts": config["punt_categories"], "by_strategy": by_strategy,
        "paired_vs_user_board": comparisons,
        "limitations": [
            "Opponents are synthetic ESPN draft/ROTO followers with stochastic rank deviations.",
            "ESPN market pick is a blended indicator, not observed survival in this private league.",
            "Matchups use projected season totals with GP/stat noise, not weekly schedule.",
            "DD values are derived estimates; board fallback is the four-punt heuristic.",
        ],
    }


def run(smoke=False):
    config = settings()
    if smoke:
        config = {**config, "runs": 2, "workers": 2, "output": config["output"] + "-smoke"}
    output = ROOT / config["output"]
    provenance = fingerprint(config)
    manifest = {"provenance": provenance, "config": config, "status": "EXPLORATORY_NO_TRAINING"}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Audit provenance changed; refusing incompatible resume")
    else:
        save(manifest_path, manifest)
    rows, remaining = [], []
    for index in range(config["runs"]):
        path = output / "scenarios" / f"run-{index:04d}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["run"] != index or set(row["strategies"]) != {item["id"] for item in strategies(config)}:
                raise ValueError(f"Incompatible scenario shard: {path}")
            rows.append(row)
        else:
            remaining.append(index)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=initialize,
                             initargs=(config,)) as pool:
        pending = {pool.submit(evaluate_run, index): index for index in remaining}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(output / "scenarios" / f"run-{index:04d}.json", row)
            count = len(remaining) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": config["runs"],
                "eta_seconds": (time.monotonic() - started) / count * len(pending) if count else None})
    result = summarize(rows, config)
    result["provenance"] = provenance
    save(output / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.execute or args.smoke:
        result = run(args.smoke)
        print(json.dumps({"status": result["status"], "runs": result["runs"],
                          "h2h": {key: value["metrics"]["matchup_win_rate"]
                                  for key, value in result["by_strategy"].items()}}, indent=2), flush=True)
    else:
        config = settings()
        print(json.dumps({"status": "PREPARED_NOT_STARTED", "runs": config["runs"],
                          "strategies": [item["id"] for item in strategies(config)]}, indent=2))
