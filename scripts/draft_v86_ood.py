"""Frozen V8.5 action ranker under model-driven opponent draft policies.

This is an external-policy test, not a training or deployment stage. State shards
are written atomically and can be resumed only with identical provenance.
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

import joblib
import numpy as np

from scripts import draft_v81_multiformat as v81
from scripts import draft_v83_distributional as v83
from scripts import draft_v84_robust_pilot as pilot
from scripts import draft_v85_action_data as data
from scripts import draft_v85_action_train as train
from scripts.run_v74_resilient import resilient_json as save

CONFIG = ROOT / "configs/draft_ml_v86_ood.json"
FIELDS = ("model_top1", "model_top3")


def settings():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def model_path():
    return ROOT / data.settings()["output"] / "training" / "ensemble.joblib"


def fingerprint(config):
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    for path in (CONFIG, Path(__file__), Path(pilot.__file__), Path(data.__file__),
                 Path(train.__file__), Path(v81.__file__), Path(v83.__file__),
                 ROOT / "web/backend/services/draft_ml/v8_state.py", model_path(),
                 ROOT / v83.configuration()[0]["snapshot"],
                 ROOT / v83.configuration()[0]["champion"]):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def model_opponent_action(state, key, field, rollout, probabilities):
    order, _ = v81.network_order(state, v81.CTX[3]["v81"])
    if field == "model_top1" or len(order) == 1:
        return order[0]
    rng = random.Random(f"{key}:{field}:{rollout}:pick{state.pick}")
    top = order[:min(3, len(order))]
    weights = probabilities[:len(top)]
    return rng.choices(top, weights=weights, k=1)[0]


def rollout_h2h(state, case, hero, action, key, field, rollout, config):
    future = state.clone()
    future.apply(action)
    while not future.complete:
        if future.slot == hero:
            pick = v81.network_order(future, v81.CTX[3]["v81"])[0][0]
        else:
            pick = model_opponent_action(future, key, field, rollout,
                                         config["model_top3_probabilities"])
        future.apply(pick)
    ncat = len(case["categories"])
    outcomes = [future.targets(hero, f"{key}:{field}:{rollout}:draw{draw}", .12, .08)
                for draw in range(config["terminal_draws"])]
    return float(np.mean([outcome[ncat + 3] + .5 * outcome[ncat + 4]
                          for outcome in outcomes]))


def evaluate_job(job, config, proposed):
    case, completed, replicate = job
    seat = config["hero_seat"]
    state, scores, key = pilot.initial_state(case, seat, completed, replicate, config)
    baseline, candidates = pilot.candidate_actions(state, scores, config["candidate_limit"])
    names = [state.players[index]["name"] for index in candidates]
    if names != proposed["candidate_names"] or \
            state.players[baseline]["name"] != proposed["baseline"]:
        raise ValueError("Candidate or baseline changed after proposal freeze")
    selected = candidates[proposed["selected_position"]]
    deltas = {}
    for field in FIELDS:
        samples = []
        for rollout in range(config["rollouts_per_field"]):
            old = rollout_h2h(state, case, seat, baseline, key, field, rollout, config)
            new = old if selected == baseline else rollout_h2h(
                state, case, seat, selected, key, field, rollout, config)
            samples.append(new - old)
        deltas[field] = samples
    return {"completed_hero_picks": completed, "replicate": replicate,
            "baseline": proposed["baseline"], "selected": proposed["selected"],
            "predicted_gain": proposed["predicted_gain"],
            "positive_votes": proposed["positive_votes"],
            "independent_h2h_delta_samples": deltas,
            "independent_h2h_delta": float(np.mean([value for field in FIELDS
                                                     for value in deltas[field]]))}


def proposals(config, jobs, ensemble):
    v83.initialize()
    result = []
    for case, completed, replicate in jobs:
        state, scores, _ = pilot.initial_state(case, config["hero_seat"],
                                                completed, replicate, config)
        baseline, candidates = pilot.candidate_actions(state, scores,
                                                        config["candidate_limit"])
        row = {"features": data.state_features(state, candidates, baseline, scores).tolist(),
               "baseline_position": candidates.index(baseline)}
        selected_position, predicted_gain, votes = train.select_action(row, ensemble)
        names = [state.players[index]["name"] for index in candidates]
        result.append({"completed_hero_picks": completed, "replicate": replicate,
                       "candidate_names": names, "baseline": names[row["baseline_position"]],
                       "selected": names[selected_position],
                       "selected_position": selected_position,
                       "predicted_gain": predicted_gain, "positive_votes": votes})
    return result


def summarize(rows):
    pooled = pilot.interval([row["independent_h2h_delta"] for row in rows])
    fields = {field: pilot.interval([
        float(np.mean(row["independent_h2h_delta_samples"][field])) for row in rows])
        for field in FIELDS}
    rounds = {str(completed): pilot.interval([
        row["independent_h2h_delta"] for row in rows
        if row["completed_hero_picks"] == completed])
        for completed in sorted({row["completed_hero_picks"] for row in rows})}
    changed = sum(row["baseline"] != row["selected"] for row in rows)
    checks = {"pooled_lower_ci_positive": pooled["ci95"][0] > 0,
              "both_model_fields_positive": all(fields[field]["mean"] > 0 for field in FIELDS),
              "changed_at_least_four": changed >= 4}
    return {"states": len(rows), "changed_picks": changed, "h2h": pooled,
            "by_opponent_field": fields, "by_completed_hero_picks": rounds,
            "checks": checks, "passed": all(checks.values()),
            "decision": "MODEL_POLICY_ROBUSTNESS_PASSED" if all(checks.values()) else
                        "KEEP_EXPERIMENTAL_NO_DEPLOYMENT"}


def run(smoke=False):
    config = settings()
    if smoke:
        config = {**config, "completed_hero_picks": [0, 7],
                  "replicates_per_round": 1, "rollouts_per_field": 1,
                  "terminal_draws": 1, "workers": 2,
                  "output": config["output"] + "-smoke"}
    if not model_path().is_file():
        raise FileNotFoundError(model_path())
    ensemble = joblib.load(model_path())
    if ensemble["data_provenance"] != data.fingerprint(data.settings()):
        raise ValueError("Frozen V8.5 model provenance mismatch")
    case = next(case for case in v83.formats() if case["id"] == config["format_id"])
    jobs = [(case, completed, 3000 + offset)
            for completed in config["completed_hero_picks"]
            for offset in range(config["replicates_per_round"])]
    selected = proposals(config, jobs, ensemble)
    output = ROOT / config["output"]
    provenance = fingerprint(config)
    manifest = {"provenance": provenance, "config": config, "proposals": selected,
                "status": "EXPERIMENTAL_NO_DEPLOYMENT"}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("OOD provenance or selections changed; refusing resume")
    else:
        save(manifest_path, manifest)
    rows, remaining = [], []
    for job, proposal in zip(jobs, selected):
        path = output / "states" / f"after{job[1]:02d}-rep{job[2]:04d}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["selected"] != proposal["selected"] or any(
                    len(row["independent_h2h_delta_samples"][field]) !=
                    config["rollouts_per_field"] for field in FIELDS):
                raise ValueError(f"Incompatible OOD shard: {path}")
            rows.append(row)
        else:
            remaining.append((job, proposal))
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(evaluate_job, job, config, proposal): (job, proposal)
                   for job, proposal in remaining}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                job, _ = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(output / "states" / f"after{job[1]:02d}-rep{job[2]:04d}.json", row)
            count = len(remaining) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": len(jobs),
                "eta_seconds": (time.monotonic() - started) / count * len(pending)
                if count else None})
    summary = summarize(rows)
    summary["provenance"] = provenance
    summary["model_sha256"] = hashlib.sha256(model_path().read_bytes()).hexdigest()
    save(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.execute or args.smoke:
        print(json.dumps(run(smoke=args.smoke), indent=2), flush=True)
    else:
        config = settings()
        print(json.dumps({"status": "PREPARED_NOT_STARTED",
                          "states": len(config["completed_hero_picks"]) *
                                    config["replicates_per_round"],
                          "rollouts_per_state": len(FIELDS) * config["rollouts_per_field"],
                          "output": str(ROOT / config["output"])}, indent=2))
