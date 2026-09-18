"""V8.2.6: independently confirm only ambiguous punt profiles and emit soft labels."""
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

from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v824_label_audit as base_audit
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha

CONFIG = ROOT / "configs/draft_ml_v826_adaptive_labels.json"
CTX = None


def configuration():
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    return settings, ROOT / settings["output"], ROOT / settings["base_output"]


def fingerprint():
    settings, _, base = configuration()
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    for path in (Path(__file__), CONFIG, ROOT / settings["champion"], ROOT / settings["snapshot"],
                 base / "summary.json", base / "raw/complete.json"):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(sha(path).encode())
    return digest.hexdigest()


def initialize():
    global CTX
    settings, _, _ = configuration()
    v81.initialize(str(ROOT / settings["champion"]))
    config, inherited, _, policies = v81.CTX
    snapshot = json.loads((ROOT / settings["snapshot"]).read_text(encoding="utf-8"))
    if snapshot.get("season") != 2027 or snapshot.get("period") != "2027_projected":
        raise ValueError("V8.2.6 requires genuine 2027 projections")
    if snapshot.get("previous_season_fallback") is not False:
        raise ValueError("Fallback-contaminated snapshot is forbidden")
    v81.CTX = config, inherited, snapshot, policies
    v81.PLAYER_CACHE = {}
    v82.CTX = {"settings": settings, "strategy": None}
    base_audit.CTX = {"settings": settings}
    CTX = settings


def utility_rows(directory: Path, profile_count: int):
    rows = []
    for profile_index in range(profile_count):
        with np.load(directory / f"profile-{profile_index:02d}.npz", allow_pickle=False) as data:
            rows.append(data["utilities"].mean(1))
    return np.stack(rows)


def needs_confirmation(row, settings):
    return (not row["best_vs_no_punt_resolved"] or
            row["full_top_second_gap"] < settings["target_gap"] or
            not all(row["cross_selected_positive"]) or
            max(row["cross_regrets"]) > settings["target_regret"])


def select_contenders(values, no_punt, settings):
    means = values.mean(1)
    best = int(means.argmax())
    paired = values - values[best]
    se = paired.std(1, ddof=1) / np.sqrt(values.shape[1])
    keep = {index for index in range(len(means))
            if means[index] + 1.96 * se[index] >= means[best] - settings["paired_screen_margin"]}
    keep.update(int(index) for index in np.argsort(means)[-settings["minimum_contenders"]:])
    keep.add(no_punt)
    return sorted(keep)


def selection_plan(settings, out, base, expected):
    summary = json.loads((base / "summary.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in base_audit.audit_formats()}
    states = []
    for row in summary["states"]:
        manifest = json.loads((base / "raw" / row["state_id"] / "manifest.json").read_text(encoding="utf-8"))
        if not needs_confirmation(row, settings):
            continue
        values = utility_rows(base / "raw" / row["state_id"], len(manifest["profiles"]))
        no_punt = manifest["profiles"].index([])
        contenders = select_contenders(values, no_punt, settings)
        states.append({
            "state_id": row["state_id"], "format_id": row["format_id"],
            "category_count": row["category_count"], "team_count": row["team_count"],
            "state_index": row["state_index"], "scenario": manifest["scenario"],
            "profiles": manifest["profiles"], "contenders": contenders,
        })
    payload = {"provenance": expected, "base_provenance": summary["provenance"], "states": states}
    save(out / "selection.json", payload)
    return payload, cases


def atomic_npz(path, **payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **payload)
    os.replace(temporary, path)


def confirm_profile(job):
    case, state_index, profile_index, profile, scenario, path, expected = job
    state, hero, opponents, key = v82.starting_state(case, state_index, "v824_label_reliability")
    if key != scenario:
        raise ValueError(f"Scenario drift: {key} != {scenario}")
    outcomes, utilities = [], []
    for rollout in range(CTX["base_rollouts"], CTX["base_rollouts"] + CTX["confirmation_rollouts"]):
        draws = base_audit.finish_draws(state.clone(), hero, opponents, key, tuple(profile), rollout)
        outcomes.append(draws)
        utilities.append([v82.outcome_utility(draw, len(case["categories"])) for draw in draws])
    atomic_npz(path, outcomes=np.stack(outcomes), utilities=np.asarray(utilities, np.float32),
               profile=np.asarray(json.dumps(profile)), profile_index=np.asarray(profile_index),
               scenario=np.asarray(key), provenance=np.asarray(expected))
    return str(path)


def enumerate_jobs(settings, out, selection, cases, expected):
    jobs, existing = [], 0
    for state in selection["states"]:
        case = cases[state["format_id"]]
        for profile_index in state["contenders"]:
            profile = state["profiles"][profile_index]
            path = out / "confirmation" / state["state_id"] / f"profile-{profile_index:02d}.npz"
            if path.exists():
                with np.load(path, allow_pickle=False) as data:
                    valid = (str(data["provenance"]) == expected and
                             int(data["profile_index"]) == profile_index and
                             json.loads(str(data["profile"])) == profile and
                             data["utilities"].shape == (settings["confirmation_rollouts"], settings["terminal_draws"]))
                if not valid:
                    raise ValueError(f"Incompatible confirmation shard: {path}")
                existing += 1
            else:
                jobs.append((case, state["state_index"], profile_index, profile,
                             state["scenario"], str(path), expected))
    return jobs, existing


def generate(settings, out, base, expected):
    selection, cases = selection_plan(settings, out, base, expected)
    jobs, existing = enumerate_jobs(settings, out, selection, cases, expected)
    total = existing + len(jobs); done = 0; started = time.monotonic()
    with ProcessPoolExecutor(max_workers=settings["workers"], initializer=initialize) as pool:
        pending = {pool.submit(confirm_profile, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                future.result(); done += 1
            elapsed = time.monotonic() - started
            progress = {"stage": "generate", "completed": existing + done, "total": total,
                        "eta_seconds": elapsed / done * (len(jobs) - done) if done else None}
            save(out / "stage-progress.json", progress)
            print(json.dumps(progress), flush=True)
    save(out / "confirmation/complete.json", {"provenance": expected,
         "states": len(selection["states"]), "profiles": total,
         "draft_continuations": total * settings["confirmation_rollouts"],
         "terminal_outcomes": total * settings["confirmation_rollouts"] * settings["terminal_draws"]})


def confirmation_values(out, state):
    rows = []
    for profile_index in state["contenders"]:
        with np.load(out / "confirmation" / state["state_id"] / f"profile-{profile_index:02d}.npz",
                     allow_pickle=False) as data:
            rows.append(data["utilities"].mean(1))
    return np.stack(rows)


def distributional_state(state, values, settings, expected):
    profiles = [state["profiles"][index] for index in state["contenders"]]
    no_punt = profiles.index([])
    half = values.shape[1] // 2
    first, second, full = values[:, :half].mean(1), values[:, half:].mean(1), values.mean(1)
    first_best, second_best, best = int(first.argmax()), int(second.argmax()), int(full.argmax())
    cross_regrets = [float(second.max() - second[first_best]), float(first.max() - first[second_best])]
    cross_positive = [bool(second[first_best] > second[no_punt]), bool(first[second_best] > first[no_punt])]
    paired = values[best] - values[no_punt]
    z = settings["decision"]["confidence_z"]
    margin = z * float(paired.std(ddof=1)) / np.sqrt(len(paired))
    rng = np.random.default_rng(int(hashlib.sha256(f"{expected}:{state['state_id']}".encode()).hexdigest()[:16], 16))
    counts = np.zeros(len(profiles), dtype=np.int32)
    for _ in range(settings["bootstrap_samples"]):
        sample = rng.integers(0, values.shape[1], values.shape[1])
        counts[int(values[:, sample].mean(1).argmax())] += 1
    labels = []
    for index, profile in enumerate(profiles):
        delta = values[index] - values[no_punt]
        labels.append({"profile": profile, "mean_utility": float(full[index]),
            "utility_std": float(values[index].std(ddof=1)),
            "probability_best": float(counts[index] / settings["bootstrap_samples"]),
            "probability_over_no_punt": float(np.mean(delta > 0)),
            "delta_no_punt_quantiles": [float(value) for value in np.quantile(delta, [.025, .5, .975])]})
    committed = (best != no_punt and float(paired.mean() - margin) > 0 and
                 float(np.mean(paired > 0)) >= settings["decision"]["probability_over_no_punt"])
    return {**{key: state[key] for key in ("state_id", "format_id", "category_count", "team_count", "state_index")},
        "source": "independent_adaptive_confirmation", "rollouts": values.shape[1],
        "candidate_count": len(profiles), "best_profile": profiles[best],
        "decision_profile": profiles[best] if committed else [], "decision": "commit" if committed else "stay_open",
        "best_probability": float(counts[best] / settings["bootstrap_samples"]),
        "best_vs_no_punt_interval": [float(paired.mean() - margin), float(paired.mean() + margin)],
        "cross_regrets": cross_regrets, "cross_selected_positive": cross_positive,
        "top1_agreement": first_best == second_best, "labels": labels}


def aggregate(rows):
    return {"states": len(rows), "top1_agreement": float(np.mean([row["top1_agreement"] for row in rows])),
        "cross_selected_positive": float(np.mean([value for row in rows for value in row["cross_selected_positive"]])),
        "mean_cross_regret": float(np.mean([value for row in rows for value in row["cross_regrets"]])),
        "p90_cross_regret": float(np.quantile([value for row in rows for value in row["cross_regrets"]], .9)),
        "commit_rate": float(np.mean([row["decision"] == "commit" for row in rows])),
        "mean_candidates": float(np.mean([row["candidate_count"] for row in rows]))}


def analyze(settings, out, base, expected):
    selection = json.loads((out / "selection.json").read_text(encoding="utf-8"))
    if selection["provenance"] != expected:
        raise ValueError("Selection provenance mismatch")
    rows = [distributional_state(state, confirmation_values(out, state), settings, expected)
            for state in selection["states"]]
    overall = aggregate(rows)
    by_category = {str(count): aggregate([row for row in rows if row["category_count"] == count])
                   for count in sorted({row["category_count"] for row in rows})}
    gates = settings["reliability_gates"]
    checks = {"cross_selected_positive": overall["cross_selected_positive"] >= gates["cross_selected_positive_min"],
              "mean_cross_regret": overall["mean_cross_regret"] <= gates["mean_cross_regret_max"]}
    summary = {"passed": all(checks.values()), "checks": checks, "gates": gates,
        "overall": overall, "by_category_count": by_category, "states": rows,
        "provenance": expected, "base": str(base),
        "next_action": "train_distributional_strategy_head" if all(checks.values()) else "extend_only_unresolved_confirmations"}
    save(out / "summary.json", summary)


def phase(stage, expected):
    if fingerprint() != expected:
        raise ValueError("V8.2.6 fingerprint changed")
    settings, out, base = configuration()
    if stage == "generate":
        generate(settings, out, base, expected)
    else:
        analyze(settings, out, base, expected)


def plan():
    settings, out, base = configuration(); expected = fingerprint()
    selection, _ = selection_plan(settings, out, base, expected)
    profile_count = sum(len(state["contenders"]) for state in selection["states"])
    return {"status": "PREPARED_NOT_STARTED", "experiment": "V8.2.6 adaptive distributional labels",
        "training": False, "target_states": len(selection["states"]), "confirmation_profiles": profile_count,
        "confirmation_rollouts": settings["confirmation_rollouts"],
        "draft_continuations": profile_count * settings["confirmation_rollouts"],
        "terminal_outcomes": profile_count * settings["confirmation_rollouts"] * settings["terminal_draws"],
        "workers": settings["workers"], "hours": {"generation": [1.5, 4], "analysis": [.02, .1], "total": [1.5, 4.1]},
        "output": str(out), "auto_train": False}


def run():
    prepared = plan(); expected = fingerprint(); _, out, _ = configuration(); out.mkdir(parents=True, exist_ok=True)
    with lock(out / "run.lock"):
        journal_path = out / "run-state.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {"provenance": expected, "completed": []}
        if journal["provenance"] != expected:
            raise ValueError("Incompatible V8.2.6 resume")
        save(out / "plan.json", prepared)
        def status(name, error=None):
            save(out / "status.json", {"pid": os.getpid(), "phase": name, "completed": len(journal["completed"]),
                "total": 2, "provenance": expected, "error": error, "updated_at": time.time(), "training": False})
        child = None
        try:
            for stage in ("generate", "analyze"):
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
    parser.add_argument("--stage", choices=("generate", "analyze")); parser.add_argument("--provenance")
    args = parser.parse_args()
    if args.stage: initialize(); phase(args.stage, args.provenance)
    elif args.execute: run()
    else: print(json.dumps(plan(), indent=2))
