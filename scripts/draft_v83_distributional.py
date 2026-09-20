"""V8.3 adaptive-label generation, distributional strategy training and sealed evaluation."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v824_label_audit as audit
from scripts import draft_v826_adaptive_labels as adaptive
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha
from web.backend.services.draft_ml.v83_strategy import DistributionalStrategyEnsemble, fit_distributional_strategy

CONFIG = ROOT / "configs/draft_ml_v83_distributional.json"
CTX = None


def configuration():
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    return settings, ROOT / settings["output"]


def formats():
    settings, _ = configuration()
    return audit.audit_formats() + [settings["target_format"]]


def holdout_formats():
    settings, _ = configuration()
    target = {**settings["target_format"], "id": "holdout-" + settings["target_format"]["id"]}
    return v81.configuration()[1]["holdout_formats"] + [target]


def fingerprint():
    settings, _ = configuration(); digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    paths = [Path(__file__), CONFIG, ROOT / "web/backend/services/draft_ml/v83_strategy.py",
             ROOT / "scripts/draft_v826_adaptive_labels.py", ROOT / "scripts/draft_v82_auto_strategy.py",
             ROOT / "scripts/draft_v81_multiformat.py", ROOT / "configs/draft_ml_v81.json",
             ROOT / "web/backend/services/draft_ml/v8_state.py",
             ROOT / settings["champion"], ROOT / settings["snapshot"], ROOT / settings["method_evidence"]]
    paths.extend(ROOT / path for path in settings["warm_starts"])
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode()); digest.update(sha(path).encode())
    return digest.hexdigest()


def initialize(checkpoints=None):
    global CTX
    settings, _ = configuration(); v81.initialize(str(ROOT / settings["champion"]))
    config, inherited, _, policies = v81.CTX
    snapshot = json.loads((ROOT / settings["snapshot"]).read_text(encoding="utf-8"))
    if snapshot.get("season") != 2027 or snapshot.get("period") != "2027_projected" or \
            snapshot.get("previous_season_fallback") is not False:
        raise ValueError("V8.3 requires uncontaminated ESPN 2027 projections")
    v81.CTX = config, inherited, snapshot, policies; v81.PLAYER_CACHE = {}
    v82.CTX = {"settings": settings, "strategy": None}; audit.CTX = {"settings": settings}
    CTX = {"settings": settings,
           "ensemble": DistributionalStrategyEnsemble(checkpoints) if checkpoints else None}


def atomic_npz(path, **payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle: np.savez_compressed(handle, **payload)
    os.replace(temporary, path)


def rollout_utilities(state, hero, opponents, key, case, profile, start, count):
    rows = []
    for rollout in range(start, start + count):
        draws = audit.finish_draws(state.clone(), hero, opponents, key, tuple(profile), rollout)
        rows.append(np.mean([outcome_utility(draw, len(case["categories"])) for draw in draws]))
    return np.asarray(rows, dtype=np.float32)


def outcome_utility(target, count):
    """Optimize H2H majority first; category volume is supporting evidence."""
    settings, _ = configuration()
    weights = settings["objective"]
    if len(target) < count + 7:
        raise ValueError("V8.3 requires H2H-aware terminal targets")
    rank, top_four, top_one = target[count:count + 3]
    win_rate, tie_rate, decisive_rate, normalized_margin = target[count + 3:count + 7]
    return float(
        weights["h2h_result"] * (win_rate + .5 * tie_rate)
        + weights["decisive_win"] * decisive_rate
        + weights["category_strength"] * np.mean(target[:count])
        + weights["matchup_margin"] * (.5 + normalized_margin)
        + weights["league_rank"] * (1.0 - rank)
        + weights["top_four"] * top_four
        + weights["top_one"] * top_one
    )


def label_state(job):
    split, case, index, path, expected = job; settings = CTX["settings"]
    state, hero, opponents, key = v82.starting_state(case, index, split)
    profiles = [list(profile) for profile in v82.shortlist(state, case, settings)]
    if len(profiles) != settings["shortlist"] or profiles[0] != []:
        raise ValueError(f"Unexpected V8.3 shortlist: {case['id']}:{index}")
    feature_rows = [v82.state_features(state, case, tuple(profile)) for profile in profiles]
    screen = np.stack([rollout_utilities(state, hero, opponents, key, case, profile, 0,
                                         settings["screen_rollouts"]) for profile in profiles])
    no_punt = profiles.index([])
    contender_settings = {**settings, "base_rollouts": settings["screen_rollouts"]}
    contenders = adaptive.select_contenders(screen, no_punt, contender_settings)
    confirmation = np.stack([rollout_utilities(state, hero, opponents, key, case, profiles[profile_index],
        settings["screen_rollouts"], settings["confirmation_rollouts"]) for profile_index in contenders])
    utility_mean = screen.mean(1); utility_std = screen.std(1, ddof=1)
    confirmed = np.zeros(len(profiles), dtype=np.bool_)
    for local, profile_index in enumerate(contenders):
        confirmed[profile_index] = True; utility_mean[profile_index] = confirmation[local].mean()
        utility_std[profile_index] = confirmation[local].std(ddof=1)
    local_no_punt = contenders.index(no_punt); best_local = int(confirmation.mean(1).argmax())
    rng = np.random.default_rng(int(hashlib.sha256(f"{expected}:{key}".encode()).hexdigest()[:16], 16))
    counts = np.zeros(len(profiles), dtype=np.int32)
    for _ in range(settings["bootstrap_samples"]):
        sample = rng.integers(0, confirmation.shape[1], confirmation.shape[1])
        counts[contenders[int(confirmation[:, sample].mean(1).argmax())]] += 1
    best_probability = counts.astype(np.float32) / settings["bootstrap_samples"]
    edge_probability = np.zeros(len(profiles), dtype=np.float32); edge_probability[no_punt] = .5
    for local, profile_index in enumerate(contenders):
        if profile_index != no_punt:
            edge_probability[profile_index] = np.mean(confirmation[local] > confirmation[local_no_punt])
    paired = confirmation[best_local] - confirmation[local_no_punt]
    margin = settings["decision"]["confidence_z"] * paired.std(ddof=1) / np.sqrt(len(paired))
    committed = (contenders[best_local] != no_punt and paired.mean() - margin > 0 and
                 np.mean(paired > 0) >= settings["decision"]["probability_over_no_punt"])
    safe_index = contenders[best_local] if committed else no_punt
    atomic_npz(path, features=np.stack([row[0] for row in feature_rows]),
        masks=np.stack([row[1] for row in feature_rows]), globals=np.stack([row[2] for row in feature_rows]),
        utility_mean=utility_mean.astype(np.float32), utility_std=utility_std.astype(np.float32),
        best_probability=best_probability, edge_probability=edge_probability, confirmed=confirmed,
        safe_index=np.asarray(safe_index, dtype=np.int64), profiles=np.asarray(json.dumps(profiles)),
        contenders=np.asarray(contenders, dtype=np.int16), scenario=np.asarray(key), format_id=np.asarray(case["id"]),
        category_count=np.asarray(len(case["categories"])), provenance=np.asarray(expected))
    return {"format_id": case["id"], "safe_profile": profiles[safe_index], "contenders": len(contenders),
            "committed": committed}


def parallel_labels(settings, jobs, out, total, existing):
    started = time.monotonic(); done = 0; rows = []
    with ProcessPoolExecutor(max_workers=settings["workers"], initializer=initialize) as pool:
        pending = {pool.submit(label_state, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready: rows.append(future.result()); done += 1
            elapsed = time.monotonic() - started
            progress = {"stage": "generate", "completed": existing + done, "total": total,
                        "eta_seconds": elapsed / done * (len(jobs) - done) if done else None}
            save(out / "stage-progress.json", progress); print(json.dumps(progress), flush=True)
    return rows


def generate(settings, out, expected):
    jobs = []; total = 0; existing = 0
    for split, count_key in (("train", "train_states_per_format"), ("validation", "validation_states_per_format")):
        for case in formats():
            for index in range(settings[count_key]):
                total += 1; path = out / "data" / split / f"{case['id']}-{index:04d}.npz"
                wanted = f"v82:{settings['seed']}:{split}:{case['id']}:{index}"
                if path.exists():
                    with np.load(path, allow_pickle=False) as data:
                        valid = str(data["provenance"]) == expected and str(data["scenario"]) == wanted
                    if not valid: raise ValueError(f"Incompatible V8.3 label shard: {path}")
                    existing += 1
                else: jobs.append((split, case, index, str(path), expected))
    rows = parallel_labels(settings, jobs, out, total, existing)
    save(out / "data/complete.json", {"provenance": expected, "shards": total, "new_shards": len(jobs),
        "screen_continuations": total * settings["shortlist"] * settings["screen_rollouts"],
        "new_rows": rows})


def checkpoints(settings, out):
    return [out / "training" / f"seed-{seed}" / "best.pt" for seed in settings["training_seeds"]]


def train(settings, out, expected):
    for seed, warm_start in zip(settings["training_seeds"], settings["warm_starts"]):
        fit_distributional_strategy(settings, out / "data", out / "training" / f"seed-{seed}",
                                    expected, seed, ROOT / warm_start)


def select_profile(scores, edges, profiles, confidence):
    mean = scores.mean(0); winner = int(mean.argmax()); no_punt = profiles.index(())
    votes = int((scores.argmax(1) == winner).sum()); edge = float(edges[:, winner].mean())
    if (winner == no_punt or votes < confidence["minimum_votes"] or
            edge < confidence["edge_probability"] or mean[winner] - mean[no_punt] < confidence["score_margin"]):
        return (), {"edge": edge, "votes": votes, "margin": float(mean[winner] - mean[no_punt])}
    return profiles[winner], {"edge": edge, "votes": votes, "margin": float(mean[winner] - mean[no_punt])}


def choose(state, case, confidence):
    profiles = v82.profiles(case, CTX["settings"]); feature_rows = [v82.state_features(state, case, p) for p in profiles]
    scores, edges = CTX["ensemble"].predict(np.stack([row[0] for row in feature_rows]),
        np.stack([row[1] for row in feature_rows]), np.stack([row[2] for row in feature_rows]))
    return select_profile(scores, edges, profiles, confidence)


def evaluation_episode(job):
    split, case, index, confidence = job; results = {}; selected = {}; confidence_rows = {}
    for mode in ("balanced", "auto"):
        state, hero, opponents, key = v82.starting_state(case, index, split)
        profile, evidence = ((), {}) if mode == "balanced" else choose(state, case, confidence)
        results[mode] = v82.finish(state, hero, opponents, key, profile, 0).tolist()
        selected[mode] = profile; confidence_rows[mode] = evidence
    return {"split": split, "format_id": case["id"], "episode": index, "scenario": key,
            "categories": case["categories"], "team_count": case["team_count"],
            "results": results, "selected": selected, "confidence": confidence_rows}


def evaluation_report(rows):
    counts = {}
    for row in rows:
        key = str(tuple(row["selected"]["auto"])); counts[key] = counts.get(key, 0) + 1
    families = {str(count): v81.metric([row for row in rows if len(row["categories"]) == count], "auto", "balanced")
                for count in sorted({len(row["categories"]) for row in rows})}
    return {"primary": {"auto_vs_balanced": v81.metric(rows, "auto", "balanced", 2.2414027276)},
        "by_category_count": families, "selection_counts": counts, "unique_profiles": len(counts),
        "maximum_profile_share": max(counts.values()) / len(rows), "n_drafts": len(rows)}


def evaluate(settings, out, split, cases, cycles, confidence, expected):
    name = f"e{confidence['edge_probability']:.2f}-v{confidence['minimum_votes']}-m{confidence['score_margin']:.2f}"
    directory = out / split / name; paths = checkpoints(settings, out); checksums = [sha(path) for path in paths]
    rows = []; jobs = []; total = sum(case["team_count"] * cycles for case in cases)
    for case in cases:
        for index in range(case["team_count"] * cycles):
            path = directory / f"{case['id']}-{index:05d}.json"
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                if row["provenance"] != expected or row["checkpoint_sha256"] != checksums:
                    raise ValueError(f"Incompatible V8.3 evaluation row: {path}")
                rows.append(row)
            else: jobs.append((split, case, index, confidence))
    started = time.monotonic(); done = 0
    with ProcessPoolExecutor(max_workers=settings["workers"], initializer=initialize,
                             initargs=([str(path) for path in paths],)) as pool:
        pending = {pool.submit(evaluation_episode, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                row = future.result(); row.update(provenance=expected, checkpoint_sha256=checksums)
                rows.append(row); save(directory / f"{row['format_id']}-{row['episode']:05d}.json", row); done += 1
            elapsed = time.monotonic() - started
            save(out / "stage-progress.json", {"stage": split, "completed": total - len(jobs) + done,
                "total": total, "eta_seconds": elapsed / done * (len(jobs) - done) if done else None})
    rows.sort(key=lambda row: (row["format_id"], row["episode"]))
    summary = {**evaluation_report(rows), "confidence": confidence, "provenance": expected,
               "checkpoint_sha256": checksums}
    save(directory / "summary.json", summary); return summary


def eligible(summary, gates):
    metric = summary["primary"]["auto_vs_balanced"]["normalized_categories"]
    if metric["delta"] < gates["normalized_delta_min"] or metric["interval"][0] < gates["interval_low_min"]:
        return False
    h2h = summary["primary"]["auto_vs_balanced"]["h2h_result"]
    if h2h["delta"] < gates["h2h_delta_min"] or h2h["interval"][0] < gates["h2h_interval_low_min"]:
        return False
    if summary["maximum_profile_share"] > gates["maximum_profile_share"] or \
            summary["unique_profiles"] < gates["minimum_unique_profiles"]:
        return False
    return all(value["h2h_result"]["delta"] >= gates["family_h2h_delta_min"]
               for value in summary["by_category_count"].values())


def calibrate(settings, out, expected):
    summaries = [evaluate(settings, out, "v83_calibration", formats(), settings["validation_cycles_per_seat"],
                          confidence, expected) for confidence in settings["confidence_candidates"]]
    passing = [summary for summary in summaries if eligible(summary, settings["validation_gates"])]
    compact = [{"confidence": row["confidence"],
        "delta": row["primary"]["auto_vs_balanced"]["normalized_categories"]["delta"],
        "interval": row["primary"]["auto_vs_balanced"]["normalized_categories"]["interval"],
        "h2h_delta": row["primary"]["auto_vs_balanced"]["h2h_result"]["delta"],
        "h2h_interval": row["primary"]["auto_vs_balanced"]["h2h_result"]["interval"],
        "family_delta": {key: value["normalized_categories"]["delta"] for key, value in row["by_category_count"].items()},
        "family_h2h_delta": {key: value["h2h_result"]["delta"] for key, value in row["by_category_count"].items()},
        "unique_profiles": row["unique_profiles"], "maximum_profile_share": row["maximum_profile_share"]} for row in summaries]
    if not passing:
        save(out / "selection.json", {"passed": False, "candidates": compact,
             "gates": settings["validation_gates"], "provenance": expected}); return
    chosen = max(passing, key=lambda row: row["primary"]["auto_vs_balanced"]["h2h_result"]["interval"][0])
    save(out / "selection.json", {"passed": True, "confidence": chosen["confidence"],
         "validation": chosen["primary"], "family_validation": chosen["by_category_count"],
         "candidates": compact, "gates": settings["validation_gates"], "provenance": expected})


def holdout(settings, out, expected):
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    if not selection["passed"]: raise ValueError("V8.3 sealed holdout blocked by calibration")
    cases = holdout_formats()
    summary = evaluate(settings, out, "v83_fresh_holdout", cases, settings["holdout_cycles_per_seat"],
                       selection["confidence"], expected)
    save(out / "holdout-summary.json", summary)


def phase(stage, expected):
    if fingerprint() != expected: raise ValueError("V8.3 fingerprint changed")
    settings, out = configuration()
    if stage == "generate": generate(settings, out, expected)
    elif stage == "train": train(settings, out, expected)
    elif stage == "calibrate": calibrate(settings, out, expected)
    else: holdout(settings, out, expected)


def plan():
    settings, out = configuration(); method = json.loads((ROOT / settings["method_evidence"]).read_text(encoding="utf-8"))
    if not method.get("passed"): raise ValueError("V8.2.6 label method did not pass")
    for path in settings["warm_starts"]:
        payload = torch.load(ROOT / path, map_location="cpu", weights_only=True)
        if payload["spec"].get("architecture") != "universal_strategy_v3": raise ValueError("Bad V8.3 warm start")
    state_count = len(formats()) * (settings["train_states_per_format"] + settings["validation_states_per_format"])
    screen = state_count * settings["shortlist"] * settings["screen_rollouts"]
    estimated_contenders = state_count * 6 * settings["confirmation_rollouts"]
    calibration = sum(case["team_count"] for case in formats()) * len(settings["confidence_candidates"])
    holdout_count = sum(case["team_count"] for case in holdout_formats()) * settings["holdout_cycles_per_seat"]
    return {"status": "PREPARED_NOT_STARTED", "model": "V8.3 adaptive distributional strategy ensemble",
        "fresh_2027_projections": True, "formats": len(formats()), "label_states": state_count,
        "screen_continuations": screen, "estimated_confirmation_continuations": estimated_contenders,
        "training_seeds": len(settings["training_seeds"]), "calibration_drafts": calibration,
        "sealed_holdout_drafts": holdout_count, "target_league": settings["target_league"],
        "target_format": settings["target_format"]["id"],
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "hours": {"generation": [10, 22], "training": [.5, 2], "calibration": [2, 5],
                  "holdout": [.5, 1.5], "total": [13, 30.5]},
        "output": str(out), "auto_promote": False}


def run():
    prepared = plan(); expected = fingerprint(); settings, out = configuration(); out.mkdir(parents=True, exist_ok=True)
    with lock(out / "run.lock"):
        journal_path = out / "run-state.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"provenance": expected, "completed": []}
        if journal["provenance"] != expected: raise ValueError("Incompatible V8.3 resume")
        save(out / "plan.json", prepared)
        def status(name, error=None):
            save(out / "status.json", {"pid": os.getpid(), "phase": name, "completed": len(journal["completed"]),
                 "total": 4, "provenance": expected, "error": error, "updated_at": time.time(), "training": True})
        child = None
        try:
            for stage in ("generate", "train", "calibrate", "holdout"):
                if stage == "holdout" and not json.loads((out / "selection.json").read_text(encoding="utf-8"))["passed"]:
                    status("STOP_FOR_REVIEW"); return
                if stage in journal["completed"]: continue
                status("RUNNING:" + stage)
                with (out / f"{stage}.log").open("a", encoding="utf-8") as handle:
                    child = subprocess.Popen([sys.executable, "-u", str(Path(__file__)), "--stage", stage,
                        "--provenance", expected], cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
                    while child.poll() is None:
                        try: child.wait(timeout=15)
                        except subprocess.TimeoutExpired: status("RUNNING:" + stage)
                if child.returncode: raise RuntimeError(f"{stage} failed; progress retained")
                journal["completed"].append(stage); save(journal_path, journal)
            status("COMPLETE")
        except BaseException as exc:
            if child is not None and child.poll() is None:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
            status("FAILED", "".join(traceback.format_exception_only(type(exc), exc)).strip()); raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=("generate", "train", "calibrate", "holdout")); parser.add_argument("--provenance")
    args = parser.parse_args()
    if args.stage: initialize(); phase(args.stage, args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(), indent=2))
