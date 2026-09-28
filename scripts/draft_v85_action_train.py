"""Conservative residual action ranker with independent validation and sealed holdout."""
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

import joblib
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from scripts import draft_v83_distributional as v83
from scripts import draft_v84_robust_pilot as pilot
from scripts import draft_v85_action_data as data
from scripts.run_v74_resilient import resilient_json as save

ALPHAS = (0.1, 1.0, 10.0, 100.0, 1000.0)
ENSEMBLE_SIZE = 5
MIN_PREDICTED_GAIN = 0.015
MIN_POSITIVE_VOTES = 4


def paths():
    config = data.settings()
    output = ROOT / config["output"]
    return config, output


def data_rows(output, split):
    rows = [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((output / "states").glob(f"{split}-*.json"))]
    return rows


def check_data(config, output):
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    if manifest["provenance"] != data.fingerprint(config) or summary["provenance"] != manifest["provenance"]:
        raise ValueError("Action-data provenance mismatch")
    if summary["decision"] != "TRAIN_EXPERIMENTAL_RANKER":
        raise ValueError("Action-label quality gate failed; refusing training")
    if not summary["sealed_holdout_unopened"]:
        raise ValueError("Holdout was opened before model selection")
    train = data_rows(output, "train")
    validation = data_rows(output, "validation")
    if len(train) != config["train_replicates_per_round"] * len(config["completed_hero_picks"]) or \
            len(validation) != config["validation_replicates_per_round"] * len(config["completed_hero_picks"]):
        raise ValueError("Incomplete action-data splits")
    return train, validation, summary["feature_names"]


def pair_features(row, names):
    values = np.asarray(row["features"], dtype=np.float64)
    baseline = values[row["baseline_position"]]
    groups = {}
    for prefix in ("candidate_minus_baseline_z_", "candidate_raw_", "candidate_eligible_",
                   "roster_z_", "opponent_mean_z_", "pool_top_z_", "candidate_z_"):
        groups[prefix] = [index for index, name in enumerate(names) if name.startswith(prefix)]
    dz = values[:, groups["candidate_minus_baseline_z_"]]
    raw = values[:, groups["candidate_raw_"]] - baseline[groups["candidate_raw_"]]
    eligible = values[:, groups["candidate_eligible_"]] - baseline[groups["candidate_eligible_"]]
    scalar_names = ("candidate_logit_delta", "candidate_roto_delta",
                    "candidate_heuristic_delta", "availability_delta")
    scalar = values[:, [names.index(name) for name in scalar_names]]
    interactions = [dz * baseline[groups[prefix]] for prefix in
                    ("roster_z_", "opponent_mean_z_", "pool_top_z_", "candidate_z_")]
    interactions += [dz * baseline[names.index(name)] for name in
                     ("pick_fraction", "next_pick_gap", "completed_fraction")]
    matrix = np.concatenate([scalar, dz, raw, eligible, *interactions], axis=1)
    if not np.isfinite(matrix).all() or not np.allclose(matrix[row["baseline_position"]], 0):
        raise ValueError("Invalid baseline-relative features")
    return matrix


def labels(row):
    samples = np.stack([np.asarray(row["h2h_samples"][field], dtype=np.float64)
                        for field in pilot.FIELDS])
    means = samples.mean((0, 2))
    return means - means[row["baseline_position"]]


def training_matrix(rows, names):
    features, targets, groups, weights = [], [], [], []
    for group, row in enumerate(rows):
        matrix = pair_features(row, names)
        y = labels(row)
        for index in range(len(y)):
            if index == row["baseline_position"]:
                continue
            features.append(matrix[index])
            targets.append(y[index])
            groups.append(group)
            weights.append(1.0 / max(1, len(y) - 1))
    return (np.asarray(features), np.asarray(targets), np.asarray(groups),
            np.asarray(weights))


def fit_one(x, y, weights, alpha):
    scaler = StandardScaler(with_mean=False)
    transformed = scaler.fit_transform(x)
    model = Ridge(alpha=alpha, fit_intercept=False)
    model.fit(transformed, y, sample_weight=weights)
    return scaler, model


def choose_alpha(x, y, groups, weights):
    folds = GroupKFold(n_splits=5)
    scores = {}
    for alpha in ALPHAS:
        errors = []
        for train, validation in folds.split(x, y, groups):
            scaler, model = fit_one(x[train], y[train], weights[train], alpha)
            predictions = model.predict(scaler.transform(x[validation]))
            errors.extend((predictions - y[validation]) ** 2)
        scores[str(alpha)] = float(np.mean(errors))
    selected = min(ALPHAS, key=lambda alpha: (scores[str(alpha)], alpha))
    return selected, scores


def train():
    config, output = paths()
    rows, _, names = check_data(config, output)
    model_path = output / "training" / "ensemble.joblib"
    summary_path = output / "training" / "summary.json"
    if model_path.exists() and summary_path.exists():
        prior = json.loads(summary_path.read_text(encoding="utf-8"))
        if prior["data_provenance"] != data.fingerprint(config):
            raise ValueError("Existing action model has incompatible data provenance")
        stored = joblib.load(model_path)
        if stored["data_provenance"] != prior["data_provenance"] or stored["feature_names"] != names:
            raise ValueError("Existing action model has incompatible feature schema")
        return prior
    x, y, groups, weights = training_matrix(rows, names)
    alpha, cv_scores = choose_alpha(x, y, groups, weights)
    rng = np.random.default_rng(config["seed"] + 91)
    models = []
    unique = np.unique(groups)
    for _ in range(ENSEMBLE_SIZE):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(groups == group) for group in sampled])
        models.append(fit_one(x[indices], y[indices], weights[indices], alpha))
    ensemble = {"models": models, "feature_names": names, "data_provenance": data.fingerprint(config),
                "alpha": alpha, "min_gain": MIN_PREDICTED_GAIN,
                "minimum_votes": MIN_POSITIVE_VOTES}
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(ensemble, model_path)
    result = {"status": "TRAINED_EXPERIMENTAL_NOT_PROMOTED", "train_states": len(rows),
              "examples": len(y), "feature_count": x.shape[1], "alpha": alpha,
              "grouped_cv_mse": cv_scores, "ensemble_size": ENSEMBLE_SIZE,
              "data_provenance": ensemble["data_provenance"], "model_path": str(model_path)}
    save(summary_path, result)
    return result


def select_action(row, ensemble):
    matrix = pair_features(row, ensemble["feature_names"])
    predictions = np.stack([model.predict(scaler.transform(matrix))
                            for scaler, model in ensemble["models"]])
    mean = predictions.mean(0)
    baseline = row["baseline_position"]
    chosen = int(np.argmax(mean))
    votes = int((predictions[:, chosen] > 0).sum())
    if mean[chosen] < ensemble["min_gain"] or votes < ensemble["minimum_votes"]:
        chosen = baseline
    return chosen, float(mean[chosen]), votes


def evaluate_selected(job):
    config, split, completed, replicate, names, baseline_name, selected_name, predicted, votes = job
    case = next(case for case in v83.formats() if case["id"] == config["format_id"])
    state, scores, key = pilot.initial_state(case, config["hero_seat"], completed, replicate, config)
    baseline, candidates = pilot.candidate_actions(state, scores, config["candidate_limit"])
    available = {state.players[index]["name"]: index for index in candidates}
    if state.players[baseline]["name"] != baseline_name or selected_name not in available or \
            names != [state.players[index]["name"] for index in candidates]:
        raise ValueError("Selected candidate differs from frozen action data")
    selected = available[selected_name]
    start = config["label_rollouts_per_field"] if split == "validation" else 0
    count = config["confirmation_rollouts_per_field"]
    deltas = {}
    for field in pilot.FIELDS:
        old = pilot.evaluate_action(state, scores, case, config["hero_seat"], baseline,
                                    key, field, start, count, config)
        new = old if selected == baseline else pilot.evaluate_action(
            state, scores, case, config["hero_seat"], selected, key,
            field, start, count, config)
        deltas[field] = (new - old).tolist()
    return {"split": split, "completed_hero_picks": completed, "replicate": replicate,
            "baseline": baseline_name, "selected": selected_name,
            "predicted_gain": predicted, "positive_votes": votes,
            "independent_h2h_delta_samples": deltas,
            "independent_h2h_delta": float(np.mean([value for field in pilot.FIELDS
                                                      for value in deltas[field]]))}


def evaluation_summary(rows, split):
    pooled = pilot.interval([row["independent_h2h_delta"] for row in rows])
    fields = {field: pilot.interval([float(np.mean(row["independent_h2h_delta_samples"][field]))
                                     for row in rows]) for field in pilot.FIELDS}
    rounds = {str(round_number): pilot.interval([row["independent_h2h_delta"] for row in rows
                                                if row["completed_hero_picks"] == round_number])
              for round_number in (0, 3, 7)}
    changed = sum(row["baseline"] != row["selected"] for row in rows)
    checks = {"h2h_interval_positive": pooled["ci95"][0] > 0,
              "both_fields_positive": all(fields[field]["mean"] > 0 for field in pilot.FIELDS),
              "changed_at_least_four": changed >= 4,
              "mid_and_late_nonnegative": rounds["3"]["mean"] >= 0 and rounds["7"]["mean"] >= 0}
    return {"split": split, "states": len(rows), "h2h": pooled, "by_opponent_field": fields,
            "by_completed_hero_picks": rounds, "changed_picks": changed,
            "checks": checks, "passed": all(checks.values()),
            "decision": ("OPEN_SEALED_HOLDOUT" if split == "validation" else "CANDIDATE_FOR_USER_REVIEW")
                        if all(checks.values()) else "KEEP_FROZEN_ACTOR"}


def proposals(config, output, split, ensemble):
    if split == "validation":
        source = data_rows(output, "validation")
    else:
        v83.initialize()
        case = next(case for case in v83.formats() if case["id"] == config["format_id"])
        source = []
        for completed in config["completed_hero_picks"]:
            for offset in range(config["holdout_replicates_per_round"]):
                replicate = 2000 + offset
                state, scores, _ = pilot.initial_state(case, config["hero_seat"],
                                                        completed, replicate, config)
                baseline, candidates = pilot.candidate_actions(state, scores,
                                                                config["candidate_limit"])
                source.append({"split": "holdout", "completed_hero_picks": completed,
                               "replicate": replicate, "baseline_position": candidates.index(baseline),
                               "candidate_names": [state.players[index]["name"] for index in candidates],
                               "features": data.state_features(state, candidates, baseline, scores).tolist()})
    result = []
    for row in source:
        chosen, predicted, votes = select_action(row, ensemble)
        names = row["candidate_names"]
        result.append((config, split, row["completed_hero_picks"], row["replicate"], names,
                       names[row["baseline_position"]], names[chosen], predicted, votes))
    return result


def evaluate(split):
    config, output = paths()
    check_data(config, output)
    training = json.loads((output / "training" / "summary.json").read_text(encoding="utf-8"))
    ensemble = joblib.load(output / "training" / "ensemble.joblib")
    if training["data_provenance"] != data.fingerprint(config) or \
            ensemble["data_provenance"] != training["data_provenance"]:
        raise ValueError("Model provenance mismatch")
    if split == "holdout":
        validation = json.loads((output / "validation" / "summary.json").read_text(encoding="utf-8"))
        if not validation["passed"]:
            raise ValueError("Sealed holdout blocked by validation gate")
    jobs = proposals(config, output, split, ensemble)
    directory = output / split
    manifest = {"split": split, "data_provenance": training["data_provenance"],
                "model_sha256": hashlib.sha256((output / "training" / "ensemble.joblib").read_bytes()).hexdigest(),
                "selected": [{"completed": job[2], "replicate": job[3], "selected": job[6]}
                             for job in jobs]}
    manifest_path = directory / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Evaluation selection changed; refusing incompatible resume")
    else:
        save(manifest_path, manifest)
    rows, remaining = [], []
    for job in jobs:
        path = directory / "states" / f"after{job[2]:02d}-rep{job[3]:04d}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row["selected"] != job[6] or any(len(row["independent_h2h_delta_samples"][field]) !=
                                                config["confirmation_rollouts_per_field"]
                                                for field in pilot.FIELDS):
                raise ValueError(f"Incompatible evaluation shard: {path}")
            rows.append(row)
        else:
            remaining.append(job)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=config["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(evaluate_selected, job): job for job in remaining}
        while pending:
            done, _ = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                row = future.result()
                rows.append(row)
                save(directory / "states" / f"after{job[2]:02d}-rep{job[3]:04d}.json", row)
            completed = len(remaining) - len(pending)
            save(directory / "progress.json", {"completed": len(rows), "total": len(jobs),
                "eta_seconds": (time.monotonic() - started) / completed * len(pending)
                if completed else None})
    result = evaluation_summary(rows, split)
    result["data_provenance"] = training["data_provenance"]
    save(directory / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("train", "validation", "holdout"), required=True)
    args = parser.parse_args()
    result = train() if args.stage == "train" else evaluate(args.stage)
    print(json.dumps(result, indent=2), flush=True)
