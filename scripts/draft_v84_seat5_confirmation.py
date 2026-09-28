"""Fresh, resume-safe H2H confirmation for seat 5 in the 14-team 11-cat league."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v83_distributional as v83
from scripts import draft_v84_robust_pilot as pilot
from scripts.run_v74_resilient import resilient_json as save

CONFIG = ROOT / "configs/draft_ml_v84_seat5_confirmation.json"


def summary(rows):
    pooled = pilot.interval([row["independent_h2h_delta"] for row in rows])
    fields = {field: pilot.interval([float(np.mean(row["independent_h2h_delta_samples"][field]))
                                     for row in rows]) for field in pilot.FIELDS}
    rounds = {str(round_number): pilot.interval([row["independent_h2h_delta"] for row in rows
                                                if row["completed_hero_picks"] == round_number])
              for round_number in (0, 3, 7)}
    checks = {"seat5_h2h_ci_positive": pooled["ci95"][0] > 0,
              "both_opponent_fields_positive": all(fields[field]["mean"] > 0 for field in pilot.FIELDS),
              "mid_and_late_nonnegative": rounds["3"]["mean"] >= 0 and rounds["7"]["mean"] >= 0}
    return {"states": len(rows), "seat5_h2h": pooled, "by_opponent_field": fields,
            "by_completed_hero_picks": rounds,
            "changed_picks": sum(row["baseline"] != row["selected"] for row in rows),
            "checks": checks,
            "decision": "GENERATE_TARGETED_ACTION_DATASET" if all(checks.values()) else
                        "IMPROVE_TEACHER_BEFORE_TRAINING"}


def run(smoke=False):
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    jobs = pilot.jobs_for(config)
    if smoke:
        jobs = [jobs[-1]]
        config = {**config, "screen_rollouts_per_field": 1,
                  "confirmation_rollouts_per_field": 2, "terminal_draws": 1}
    output = ROOT / config["output"]
    if smoke:
        output = output.with_name(output.name + "-smoke")
    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(pilot.fingerprint(config).encode())
    digest.update(CONFIG.read_bytes())
    digest.update(Path(__file__).read_bytes())
    provenance = digest.hexdigest()
    manifest = {"provenance": provenance, "jobs": [pilot.job_id(job) for job in jobs],
                "config": config, "status": "FRESH_SEAT5_CONFIRMATION"}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Seat-5 confirmation code or config changed; incompatible resume")
    else:
        save(manifest_path, manifest)
    rows, remaining = [], []
    for job in jobs:
        path = output / "states" / f"{pilot.job_id(job)}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["format_id"], row["seat"], row["completed_hero_picks"], row["replicate"]) != \
                    (job[0]["id"], job[1], job[2], job[3]):
                raise ValueError(f"Incompatible seat-5 shard: {path}")
            if any(len(row["independent_h2h_delta_samples"][field]) !=
                   config["confirmation_rollouts_per_field"] for field in pilot.FIELDS):
                raise ValueError(f"Incomplete seat-5 shard: {path}")
            rows.append(row)
        else:
            remaining.append(job)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(pilot.evaluate_job, job, config): job for job in remaining}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(output / "states" / f"{pilot.job_id(job)}.json", row)
            completed = len(remaining) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": len(jobs),
                "eta_seconds": (time.monotonic() - started) / completed * len(pending)
                if completed else None})
    result = ({"states": len(rows), "smoke": True, "outcomes": rows} if smoke
              else summary(rows))
    result["provenance"] = provenance
    save(output / "summary.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.execute or args.smoke:
        run(args.smoke)
    else:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        print(json.dumps({"status": "PREPARED_NOT_STARTED", "states": len(pilot.jobs_for(config)),
                          "screen_rollouts_per_field": config["screen_rollouts_per_field"],
                          "confirmation_rollouts_per_field": config["confirmation_rollouts_per_field"],
                          "output": str(ROOT / config["output"])}, indent=2))
