"""Resume-safe, multi-round H2H action-search pilot against two opponent fields.

Exploratory gate only. It does not train or promote a model, and the independent
confirmation rollouts are never used to choose the action within a state.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v81_multiformat as v81
from scripts import draft_v83_distributional as v83
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v8_state import UniversalState

CONFIG = ROOT / "configs/draft_ml_v84_robust_pilot.json"
FIELDS = ("heuristic", "roto")


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def fingerprint(config):
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    paths = (Path(__file__), CONFIG, ROOT / "scripts/draft_v81_multiformat.py",
             ROOT / "scripts/draft_v83_distributional.py",
             ROOT / "web/backend/services/draft_ml/v8_state.py",
             ROOT / v83.configuration()[0]["champion"],
             ROOT / v83.configuration()[0]["snapshot"])
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def jobs_for(config):
    cases = {case["id"]: case for case in v83.formats()}
    jobs = []
    for format_id in config["formats"]:
        case = cases[format_id]
        for completed in config["completed_hero_picks"]:
            if not 0 <= completed < len(case["slots"]):
                raise ValueError(f"Invalid completed pick count: {format_id}:{completed}")
            for seat in config["hero_seats"][format_id]:
                if not 1 <= seat <= case["team_count"]:
                    raise ValueError(f"Invalid seat: {format_id}:{seat}")
                for replicate in range(config["replicates"]):
                    jobs.append((case, seat, completed, replicate))
    return jobs


def job_id(job):
    case, seat, completed, replicate = job
    return f"{case['id']}-seat{seat:02d}-after{completed:02d}-rep{replicate:02d}"


def market_scores(state):
    return np.asarray([sum(float(player.get("z_scores", {}).get(category, 0.0))
                           for category in state.categories)
                       for player in state.players], dtype=np.float32)


def opponent_setup(state, case, key, rollout, field, config):
    rng = random.Random(f"{key}:{field}:{rollout}:opponents")
    descriptors = v81.opponent_assignments(case, f"{key}:{field}:{rollout}:styles")
    modes = {slot: (field if field != "mixed" else rng.choice(FIELDS))
             for slot in range(1, state.team_count + 1)}
    noise = {slot: np.asarray([rng.gauss(0.0, config["roto_player_noise"])
                               for _ in state.players], dtype=np.float32)
             for slot in range(1, state.team_count + 1) if modes[slot] == "roto"}
    return modes, descriptors, noise


def opponent_action(state, case, key, rollout, modes, descriptors, noise, scores):
    slot = state.slot
    if modes[slot] == "heuristic":
        descriptor = descriptors[slot]
        return v81.heuristic_action(state, descriptor["weights"],
                                    f"{key}:{rollout}:slot{slot}", descriptor)
    return max(state.legal(), key=lambda index: (float(scores[index] + noise[slot][index]), -index))


def initial_state(case, seat, completed, replicate, config):
    key = f"v84robust:{config['seed']}:{case['id']}:seat{seat}:after{completed}:rep{replicate}"
    players = v81.case_players(case)
    state = UniversalState(players, case["slots"], case["team_count"],
                           categories=case["categories"], reverse_categories=case.get("reverse", ()))
    scores = market_scores(state)
    modes, descriptors, noise = opponent_setup(state, case, key, -1, "mixed", config)
    while not state.complete:
        if state.slot == seat and len(state.rosters[seat]) >= completed:
            break
        if state.slot == seat:
            action = v81.network_order(state, v81.CTX[3]["v81"])[0][0]
        else:
            action = opponent_action(state, case, key, -1, modes, descriptors, noise, scores)
        state.apply(action)
    if state.slot != seat or state.complete:
        raise ValueError(f"Hero was not on the clock: {key}")
    return state, scores, key


def candidate_actions(state, scores, limit):
    network = v81.network_order(state, v81.CTX[3]["v81"])[0]
    weights = dict.fromkeys(state.categories, 1.0)
    heuristic_scores = v81.heuristic_scores(state, weights)
    heuristic = sorted(heuristic_scores, key=lambda index: (-heuristic_scores[index], index))
    roto = sorted(state.legal(), key=lambda index: (-float(scores[index]), index))
    candidates = list(dict.fromkeys((*network[:4], *heuristic[:3], *roto[:3])))[:limit]
    return network[0], candidates


def rollout_h2h(state, scores, case, hero, action, key, field, rollout, config):
    future = state.clone()
    future.apply(action)
    modes, descriptors, noise = opponent_setup(future, case, key, rollout, field, config)
    while not future.complete:
        if future.slot == hero:
            pick = v81.network_order(future, v81.CTX[3]["v81"])[0][0]
        else:
            pick = opponent_action(future, case, key, rollout, modes, descriptors, noise, scores)
        future.apply(pick)
    count = len(case["categories"])
    outcomes = [future.targets(hero, f"{key}:{field}:{rollout}:draw{draw}", .12, .08)
                for draw in range(config["terminal_draws"])]
    return float(np.mean([target[count + 3] + .5 * target[count + 4]
                          for target in outcomes]))


def evaluate_action(state, scores, case, hero, action, key, field, start, count, config):
    return np.asarray([rollout_h2h(state, scores, case, hero, action, key, field,
                                  rollout, config) for rollout in range(start, start + count)],
                      dtype=np.float32)


def evaluate_job(job, config):
    case, seat, completed, replicate = job
    state, scores, key = initial_state(case, seat, completed, replicate, config)
    baseline, candidates = candidate_actions(state, scores, config["candidate_limit"])
    screen_count = config["screen_rollouts_per_field"]
    screen = {action: {field: evaluate_action(state, scores, case, seat, action, key,
                                              field, 0, screen_count, config)
                       for field in FIELDS} for action in candidates}

    def field_mean(action, field):
        return float(screen[action][field].mean())

    def robust_gain(action):
        changes = [field_mean(action, field) - field_mean(baseline, field) for field in FIELDS]
        return float(np.mean(changes)), float(min(changes))

    selected = max(candidates, key=lambda action: (robust_gain(action)[0], -action))
    mean_gain, worst_field_gain = robust_gain(selected)
    if mean_gain < config["screen_min_gain"] or worst_field_gain < -config["screen_max_field_regret"]:
        selected = baseline

    confirm_count = config["confirmation_rollouts_per_field"]
    confirmation = {}
    for field in FIELDS:
        old = evaluate_action(state, scores, case, seat, baseline, key, field,
                              screen_count, confirm_count, config)
        new = old if selected == baseline else evaluate_action(
            state, scores, case, seat, selected, key, field,
            screen_count, confirm_count, config)
        confirmation[field] = (new - old).tolist()
    return {"format_id": case["id"], "seat": seat,
            "completed_hero_picks": completed, "replicate": replicate,
            "baseline": state.players[baseline]["name"],
            "selected": state.players[selected]["name"],
            "candidate_count": len(candidates),
            "screen_mean_gain": mean_gain, "screen_worst_field_gain": worst_field_gain,
            "independent_h2h_delta_samples": confirmation,
            "independent_h2h_delta": float(np.mean([value for field in FIELDS
                                                     for value in confirmation[field]]))}


def interval(values):
    data = np.asarray(values, dtype=np.float64)
    mean = float(data.mean())
    se = float(data.std(ddof=1) / np.sqrt(len(data))) if len(data) > 1 else 0.0
    return {"n": len(data), "mean": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se],
            "positive": int((data > 0).sum()), "negative": int((data < 0).sum())}


def summarize(rows):
    pooled = interval([row["independent_h2h_delta"] for row in rows])
    formats = {format_id: interval([row["independent_h2h_delta"] for row in rows
                                    if row["format_id"] == format_id])
               for format_id in sorted({row["format_id"] for row in rows})}
    fields = {field: interval([float(np.mean(row["independent_h2h_delta_samples"][field]))
                               for row in rows]) for field in FIELDS}
    rounds = {str(round_number): interval([row["independent_h2h_delta"] for row in rows
                                          if row["completed_hero_picks"] == round_number])
              for round_number in sorted({row["completed_hero_picks"] for row in rows})}
    seat_five = [row["independent_h2h_delta"] for row in rows
                 if row["format_id"] == "main-c11-t14-r13" and row["seat"] == 5]
    checks = {"pooled_ci_positive": pooled["ci95"][0] > 0,
              "target_mean_positive": formats["main-c11-t14-r13"]["mean"] > 0,
              "standard8_mean_positive": formats["s8-t10-r13"]["mean"] > 0,
              "both_fields_positive": all(fields[field]["mean"] > 0 for field in FIELDS),
              "target_seat5_nonnegative": float(np.mean(seat_five)) >= 0}
    return {"states": len(rows), "pooled": pooled, "by_format": formats,
            "by_opponent_field": fields, "by_completed_hero_picks": rounds,
            "target_seat5": interval(seat_five),
            "changed_picks": sum(row["baseline"] != row["selected"] for row in rows),
            "checks": checks,
            "decision": "PROCEED_TO_ACTION_DATASET" if all(checks.values()) else "DO_NOT_TRAIN_YET"}


def run(smoke=False):
    config = settings()
    jobs = jobs_for(config)
    if smoke:
        jobs = [jobs[0], jobs[len(jobs) // 2]]
        config = {**config, "screen_rollouts_per_field": 1,
                  "confirmation_rollouts_per_field": 2, "terminal_draws": 1}
    output = ROOT / config["output"]
    if smoke:
        output = output.with_name(output.name + "-smoke")
    output.mkdir(parents=True, exist_ok=True)
    provenance = fingerprint(config)
    manifest_path = output / "manifest.json"
    manifest = {"provenance": provenance, "jobs": [job_id(job) for job in jobs],
                "config": config, "status": "EXPLORATORY_NOT_SEALED"}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing != manifest:
            raise ValueError("Pilot configuration or code changed; refusing incompatible resume")
    else:
        save(manifest_path, manifest)
    rows = []
    pending_jobs = []
    for job in jobs:
        path = output / "states" / f"{job_id(job)}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if (row["format_id"], row["seat"], row["completed_hero_picks"], row["replicate"]) != \
                    (job[0]["id"], job[1], job[2], job[3]):
                raise ValueError(f"Incompatible pilot shard: {path}")
            if any(len(row["independent_h2h_delta_samples"][field]) !=
                   config["confirmation_rollouts_per_field"] for field in FIELDS):
                raise ValueError(f"Incomplete pilot shard: {path}")
            rows.append(row)
        else:
            pending_jobs.append(job)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(evaluate_job, job, config): job for job in pending_jobs}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(output / "states" / f"{job_id(job)}.json", row)
            newly_done = len(pending_jobs) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": len(jobs),
                "eta_seconds": (time.monotonic() - started) / newly_done * len(pending)
                if newly_done else None})
    result = summarize(rows) if not smoke else {"states": len(rows), "smoke": True,
                                               "outcomes": rows}
    result["provenance"] = provenance
    result["snapshot_market_note"] = "2027 frozen snapshot has no league-specific ESPN Player Rater; projected category ROTO is used for one opponent field"
    save(output / "summary.json", result)
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if not args.execute and not args.smoke:
        config = settings()
        print(json.dumps({"status": "PREPARED_NOT_STARTED", "states": len(jobs_for(config)),
                          "formats": config["formats"], "completed_hero_picks": config["completed_hero_picks"],
                          "workers": config["workers"], "output": str(ROOT / config["output"])}, indent=2))
    else:
        run(args.smoke)
