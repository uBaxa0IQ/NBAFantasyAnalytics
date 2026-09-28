"""Resume-safe action-level H2H labels for seat 5; sealed holdout stays unopened."""
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

from scripts import draft_v81_multiformat as v81
from scripts import draft_v83_distributional as v83
from scripts import draft_v84_robust_pilot as pilot
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v8_state import RAW_SCALES, RAW_STATS, POSITIONS, compatible

CONFIG = ROOT / "configs/draft_ml_v85_targeted_actions.json"


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def fingerprint(config):
    digest = hashlib.sha256(pilot.fingerprint(config).encode())
    digest.update(CONFIG.read_bytes())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def cases_and_jobs(config, smoke=False):
    case = next(case for case in v83.formats() if case["id"] == config["format_id"])
    train_count = config["train_replicates_per_round"]
    validation_count = config["validation_replicates_per_round"]
    jobs = []
    for completed in config["completed_hero_picks"]:
        for replicate in range(train_count):
            jobs.append(("train", case, config["hero_seat"], completed, replicate))
        for replicate in range(validation_count):
            jobs.append(("validation", case, config["hero_seat"], completed,
                         1000 + replicate))
    if smoke:
        jobs = [jobs[0], jobs[-1]]
    return jobs


def job_id(job):
    split, _, seat, completed, replicate = job
    return f"{split}-seat{seat:02d}-after{completed:02d}-rep{replicate:04d}"


def category_vector(player, categories):
    return [float(player.get("z_scores", {}).get(category, 0.0) or 0.0)
            for category in categories]


def feature_names(categories):
    names = ["pick_fraction", "completed_fraction", "next_pick_gap", "candidate_logit_delta",
             "candidate_roto_delta", "candidate_heuristic_delta", "availability_delta"]
    for prefix in ("candidate_z", "candidate_minus_baseline_z", "roster_z", "opponent_mean_z",
                   "pool_top_z"):
        names += [f"{prefix}_{category}" for category in categories]
    names += [f"candidate_raw_{name}" for name in RAW_STATS]
    names += [f"candidate_eligible_{position}" for position in POSITIONS]
    return names


def state_features(state, candidates, baseline, scores):
    categories = state.categories
    roster = state.rosters[state.slot]
    own_totals = np.asarray([sum(category_vector(state.players[index], categories)[category_index]
                                 for index in roster)
                             for category_index in range(len(categories))], dtype=np.float32)
    other_totals = np.asarray([
        [sum(category_vector(state.players[index], categories)[category_index]
             for index in rows) for category_index in range(len(categories))]
        for slot, rows in state.rosters.items() if slot != state.slot], dtype=np.float32)
    opponent_mean = other_totals.mean(0)
    remaining_z = np.asarray([category_vector(state.players[index], categories)
                              for index in state.remaining], dtype=np.float32)
    pool_top = np.sort(remaining_z, axis=0)[-min(10, len(remaining_z)):].mean(0)
    ctx = state.context()
    _, logits = v81.network_order(state, v81.CTX[3]["v81"])
    heuristic = v81.heuristic_scores(state, dict.fromkeys(categories, 1.0))
    baseline_z = np.asarray(category_vector(state.players[baseline], categories), dtype=np.float32)
    baseline_availability = float(state.players[baseline].get("availability_probability") or 0.0)
    rows = []
    for index in candidates:
        player = state.players[index]
        z = np.asarray(category_vector(player, categories), dtype=np.float32)
        raw = [float(player.get("stats", {}).get(name, 0.0) or 0.0) / scale
               for name, scale in zip(RAW_STATS, RAW_SCALES)]
        rows.append([
            state.pick / (state.team_count * state.rounds),
            len(roster) / state.rounds,
            (ctx.next_own_pick - state.pick) / (2 * state.team_count),
            float(logits[index] - logits[baseline]),
            float(scores[index] - scores[baseline]) / 10.0,
            float(heuristic[index] - heuristic[baseline]) / 10.0,
            float(player.get("availability_probability") or 0.0) - baseline_availability,
            *(z / 4.0), *((z - baseline_z) / 4.0), *(own_totals / 20.0),
            *(opponent_mean / 20.0), *(pool_top / 4.0),
            *raw, *[float(compatible(player, position)) for position in POSITIONS]])
    matrix = np.asarray(rows, dtype=np.float32)
    if not np.isfinite(matrix).all():
        raise ValueError("Non-finite action features")
    if matrix.shape[1] != len(feature_names(categories)):
        raise ValueError("Action feature schema mismatch")
    return matrix


def evaluate_job(job, config):
    split, case, seat, completed, replicate = job
    state, scores, key = pilot.initial_state(case, seat, completed, replicate, config)
    baseline, candidates = pilot.candidate_actions(state, scores, config["candidate_limit"])
    features = state_features(state, candidates, baseline, scores)
    count = config["label_rollouts_per_field"]
    samples = {field: [pilot.evaluate_action(state, scores, case, seat, index,
                                             key, field, 0, count, config).tolist()
                       for index in candidates] for field in pilot.FIELDS}
    baseline_position = candidates.index(baseline)
    return {"split": split, "format_id": case["id"], "seat": seat,
            "completed_hero_picks": completed, "replicate": replicate,
            "baseline_position": baseline_position,
            "candidate_names": [state.players[index]["name"] for index in candidates],
            "candidate_ids": [state.players[index].get("player_id", index) for index in candidates],
            "features": features.tolist(), "h2h_samples": samples,
            "state_key": key}


def reliability(rows):
    agreements, overlaps, cross_gains = [], [], []
    for row in rows:
        data = np.stack([np.asarray(row["h2h_samples"][field], dtype=np.float64)
                         for field in pilot.FIELDS])
        half = data.shape[2] // 2
        first = data[:, :, :half].mean((0, 2))
        second = data[:, :, half:].mean((0, 2))
        baseline = row["baseline_position"]
        agreements.append(int(first.argmax() == second.argmax()))
        overlaps.append(len(set(np.argsort(first)[-3:]) & set(np.argsort(second)[-3:])))
        cross_gains.append(float(second[first.argmax()] - second[baseline]))
        cross_gains.append(float(first[second.argmax()] - first[baseline]))
    return {"states": len(rows), "split_half_top1_agreement": float(np.mean(agreements)),
            "split_half_top3_overlap": float(np.mean(overlaps)),
            "cross_selected_h2h_gain": pilot.interval(cross_gains)}


def summarize(rows, config):
    by_split = {split: reliability([row for row in rows if row["split"] == split])
                for split in ("train", "validation")}
    checks = {"enough_train_states": by_split["train"]["states"] >= 40,
              "enough_validation_states": by_split["validation"]["states"] >= 15,
              "train_cross_gain_positive": by_split["train"]["cross_selected_h2h_gain"]["mean"] > 0,
              "validation_cross_gain_positive": by_split["validation"]["cross_selected_h2h_gain"]["mean"] > 0,
              "top3_overlap_at_least_one": by_split["validation"]["split_half_top3_overlap"] >= 1.0}
    return {"states": len(rows), "by_split": by_split, "checks": checks,
            "decision": "TRAIN_EXPERIMENTAL_RANKER" if all(checks.values()) else
                        "IMPROVE_ACTION_LABELS_BEFORE_TRAINING",
            "sealed_holdout_unopened": True,
            "feature_names": feature_names(v83.configuration()[0]["target_format"]["categories"])}


def run(smoke=False):
    config = settings()
    jobs = cases_and_jobs(config, smoke)
    if smoke:
        config = {**config, "label_rollouts_per_field": 2, "terminal_draws": 1}
    output = ROOT / config["output"]
    if smoke:
        output = output.with_name(output.name + "-smoke")
    output.mkdir(parents=True, exist_ok=True)
    provenance = fingerprint(config)
    manifest = {"provenance": provenance, "config": config,
                "jobs": [job_id(job) for job in jobs], "holdout_unopened": True}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Action-data code or config changed; refusing incompatible resume")
    else:
        save(manifest_path, manifest)
    rows, remaining = [], []
    for job in jobs:
        path = output / "states" / f"{job_id(job)}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["split"], row["seat"], row["completed_hero_picks"], row["replicate"]) != \
                    (job[0], job[2], job[3], job[4]):
                raise ValueError(f"Incompatible action-data shard: {path}")
            if any(len(row["h2h_samples"][field][0]) != config["label_rollouts_per_field"]
                   for field in pilot.FIELDS):
                raise ValueError(f"Incomplete action-data shard: {path}")
            rows.append(row)
        else:
            remaining.append(job)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(evaluate_job, job, config): job for job in remaining}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(output / "states" / f"{job_id(job)}.json", row)
            completed = len(remaining) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": len(jobs),
                "eta_seconds": (time.monotonic() - started) / completed * len(pending)
                if completed else None})
    result = ({"smoke": True, "states": len(rows), "feature_count": len(rows[0]["features"][0])}
              if smoke else summarize(rows, config))
    result["provenance"] = provenance
    save(output / "summary.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "feature_names"}, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.execute or args.smoke:
        run(args.smoke)
    else:
        config = settings()
        print(json.dumps({"status": "PREPARED_NOT_STARTED",
                          "states": len(cases_and_jobs(config)),
                          "holdout_replicates_unopened": config["holdout_replicates_per_round"],
                          "rollouts_per_candidate": 2 * config["label_rollouts_per_field"],
                          "output": str(ROOT / config["output"])}, indent=2))
