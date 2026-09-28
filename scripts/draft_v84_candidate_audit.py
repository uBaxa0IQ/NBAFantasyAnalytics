"""Paired, independent audit of the V8.3 strategy shortlist.

This is a gate before generating V8.4 training labels.  Both shortlists see
identical draft states and rollout seeds; selection and evaluation use disjoint
rollouts so the reported gain does not reuse the winning screen sample.
"""
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

from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v83_distributional as v83
from scripts.run_v74_resilient import resilient_json as save

OUTPUT = ROOT / "artifacts/draft_ml/v84-candidate-audit"
SCREEN_ROLLOUTS = 8
CONFIRM_ROLLOUTS = 24
TARGET_CASES = {
    "main-c11-t14-r13": (0, 4, 7, 10, 13),
    "s8-t10-r13": (0, 4, 8),
}
PRIORITY = (
    ("FT%", "3PM", "3PT%"),
    ("REB", "BLK"),
    ("STL", "BLK"),
    ("FT%", "3PM"),
    ("FG%", "3PT%"),
)


def expanded_shortlist(state, case, settings):
    categories = tuple(case["categories"])
    old = v82.shortlist(state, case, settings)
    valid = set(v82.profiles(case, settings))
    pinned = [profile for profile in PRIORITY if profile in valid]
    required = [(), *((category,) for category in categories), *pinned]
    result = list(dict.fromkeys((*required, *old)))[: settings["shortlist"]]
    if len(result) != settings["shortlist"]:
        raise ValueError("Incomplete expanded shortlist")
    return result


def fingerprint():
    digest = hashlib.sha256()
    for path in (Path(__file__), v83.CONFIG, ROOT / "scripts/draft_v83_distributional.py",
                 ROOT / "scripts/draft_v82_auto_strategy.py"):
        digest.update(path.read_bytes())
    digest.update(v83.fingerprint().encode())
    return digest.hexdigest()


def audit_state(job):
    case, index, expected = job
    state, hero, opponents, key = v82.starting_state(case, index, "v84_candidate_audit")
    settings = v83.CTX["settings"]
    old = v82.shortlist(state, case, settings)
    expanded = expanded_shortlist(state, case, settings)
    union = list(dict.fromkeys((*old, *expanded)))
    screened = {profile: v83.rollout_utilities(state, hero, opponents, key, case, profile, 0,
                                               SCREEN_ROLLOUTS) for profile in union}
    choices = {"old": max(old, key=lambda profile: float(screened[profile].mean())),
               "expanded": max(expanded, key=lambda profile: float(screened[profile].mean()))}
    check = list(dict.fromkeys(((), choices["old"], choices["expanded"])))
    confirmed = {profile: v83.rollout_utilities(state, hero, opponents, key, case, profile,
                                                SCREEN_ROLLOUTS, CONFIRM_ROLLOUTS)
                 for profile in check}
    delta = confirmed[choices["expanded"]] - confirmed[choices["old"]]
    no_punt = confirmed[()]
    return {
        "format_id": case["id"], "seat": hero, "state_index": index, "scenario": key,
        "provenance": expected, "old_candidates": [list(value) for value in old],
        "expanded_candidates": [list(value) for value in expanded],
        "old_choice": list(choices["old"]), "expanded_choice": list(choices["expanded"]),
        "independent_delta": float(delta.mean()),
        "expanded_vs_no_punt": float((confirmed[choices["expanded"]] - no_punt).mean()),
        "old_vs_no_punt": float((confirmed[choices["old"]] - no_punt).mean()),
        "independent_delta_samples": delta.tolist(),
        "triple_screened": list(PRIORITY[0]) in [list(value) for value in expanded],
    }


def summarize(rows):
    values = np.asarray([row["independent_delta"] for row in rows], dtype=np.float64)
    per_case = {}
    for case in sorted({row["format_id"] for row in rows}):
        group = [row for row in rows if row["format_id"] == case]
        per_case[case] = {
            "states": len(group),
            "mean_delta": float(np.mean([row["independent_delta"] for row in group])),
            "expanded_better_states": sum(row["independent_delta"] > 0 for row in group),
            "expanded_worse_states": sum(row["independent_delta"] < 0 for row in group),
            "triple_coverage": sum(row["triple_screened"] for row in group),
            "choices": [{"seat": row["seat"], "old": row["old_choice"],
                         "expanded": row["expanded_choice"],
                         "delta": row["independent_delta"]} for row in group],
        }
    se = float(values.std(ddof=1) / np.sqrt(len(values))) if len(values) > 1 else 0.0
    return {
        "states": len(rows), "mean_independent_delta": float(values.mean()),
        "interval_95": [float(values.mean() - 1.96 * se), float(values.mean() + 1.96 * se)],
        "expanded_better_states": int((values > 0).sum()),
        "expanded_worse_states": int((values < 0).sum()),
        "by_format": per_case,
        "decision": "EXPAND_LABEL_GENERATION" if values.mean() > 0 and
                    per_case["main-c11-t14-r13"]["mean_delta"] > 0 else "REVIEW_SHORTLIST",
        "note": "Small screening audit. Use more states before claiming model improvement.",
    }


def run():
    settings, _ = v83.configuration()
    case_by_id = {case["id"]: case for case in v83.formats()}
    unknown = set(TARGET_CASES) - set(case_by_id)
    if unknown:
        raise ValueError(f"Missing audit formats: {sorted(unknown)}")
    expected = fingerprint()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    rows = []
    for case_id, indices in TARGET_CASES.items():
        case = case_by_id[case_id]
        for index in indices:
            path = OUTPUT / "states" / f"{case_id}-{index:03d}.json"
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                if row["provenance"] != expected:
                    raise ValueError(f"Incompatible existing audit row: {path}")
                rows.append(row)
            else:
                jobs.append((case, index, expected))
    total = len(rows) + len(jobs)
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=min(settings["workers"], len(jobs) or 1), initializer=v83.initialize) as pool:
        pending = {pool.submit(audit_state, job) for job in jobs}
        done = 0
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                row = future.result()
                rows.append(row)
                save(OUTPUT / "states" / f"{row['format_id']}-{row['state_index']:03d}.json", row)
                done += 1
            save(OUTPUT / "progress.json", {"completed": len(rows), "total": total,
                 "eta_seconds": (time.monotonic() - started) / done * len(pending) if done else None})
    summary = {"provenance": expected, **summarize(rows)}
    save(OUTPUT / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        print(json.dumps(run(), indent=2), flush=True)
    else:
        print(json.dumps({"status": "PREPARED", "states": sum(map(len, TARGET_CASES.values())),
                          "screen_rollouts": SCREEN_ROLLOUTS, "confirmation_rollouts": CONFIRM_ROLLOUTS,
                          "output": str(OUTPUT)}, indent=2))
