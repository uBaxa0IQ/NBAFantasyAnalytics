"""Independent H2H test of improving the next pick, without a fixed punt."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v83_distributional as v83
from scripts import draft_v824_label_audit as audit
from scripts.run_v74_resilient import resilient_json as save

OUTPUT = ROOT / "artifacts/draft_ml/v84-action-audit"
CASE_INDICES = {"main-c11-t14-r13": (0, 4, 7, 10, 13), "s8-t10-r13": (0, 4, 8)}
CONFIRMATION_CASE_INDICES = {"main-c11-t14-r13": tuple(range(14)),
                             "s8-t10-r13": tuple(range(10))}
EXTRA_CASE_INDICES = {"main-c11-t14-r13": tuple(range(14, 28)),
                      "s8-t10-r13": tuple(range(10, 20))}
H2H_CASE_INDICES = {"main-c11-t14-r13": tuple(range(28, 42)),
                    "s8-t10-r13": tuple(range(20, 30))}
SCREEN_ROLLOUTS = 4
CONFIRM_ROLLOUTS = 16


def action_candidates(state):
    network = v81.network_order(state, v81.CTX[3]["v81"])[0]
    weights = dict.fromkeys(state.categories, 1.0)
    heuristic_scores = v81.heuristic_scores(state, weights)
    heuristic = sorted(heuristic_scores, key=lambda index: (-heuristic_scores[index], index))
    return network[0], list(dict.fromkeys((*network[:4], *heuristic[:4])))


def utility_samples(state, hero, opponents, key, case, action, start, count):
    branch = state.clone()
    branch.apply(action)
    utilities = []
    h2h_results = []
    category_count = len(case["categories"])
    for rollout in range(start, start + count):
        draws = audit.finish_draws(branch.clone(), hero, opponents, key, (), rollout)
        utilities.append(float(np.mean([v83.outcome_utility(draw, category_count) for draw in draws])))
        h2h_results.append(float(np.mean(draws[:, category_count + 3] + .5 * draws[:, category_count + 4])))
    return np.asarray(utilities, dtype=np.float32), np.asarray(h2h_results, dtype=np.float32)


def audit_state(job):
    case, index, split, screen_metric = job
    state, hero, opponents, key = v82.starting_state(case, index, split)
    if state.slot != hero:
        raise ValueError("Hero must be on the clock")
    baseline, candidates = action_candidates(state)
    screen = {action: utility_samples(state, hero, opponents, key, case, action, 0,
                                      SCREEN_ROLLOUTS) for action in candidates}
    metric_index = 1 if screen_metric == "h2h" else 0
    selected = max(candidates, key=lambda action: float(screen[action][metric_index].mean()))
    baseline_confirm = utility_samples(state, hero, opponents, key, case, baseline,
                                       SCREEN_ROLLOUTS, CONFIRM_ROLLOUTS)
    selected_confirm = (baseline_confirm if selected == baseline else
                        utility_samples(state, hero, opponents, key, case, selected,
                                        SCREEN_ROLLOUTS, CONFIRM_ROLLOUTS))
    delta = selected_confirm[0] - baseline_confirm[0]
    h2h_delta = selected_confirm[1] - baseline_confirm[1]
    return {"format_id": case["id"], "seat": hero, "state_index": index,
            "screen_metric": screen_metric,
            "baseline": state.players[baseline]["name"],
            "selected": state.players[selected]["name"],
            "candidate_names": [state.players[action]["name"] for action in candidates],
            "independent_delta": float(delta.mean()),
            "independent_delta_samples": delta.tolist(),
            "independent_h2h_delta": float(h2h_delta.mean()),
            "independent_h2h_delta_samples": h2h_delta.tolist()}


def summarize(rows):
    deltas = np.asarray([row["independent_delta"] for row in rows], dtype=np.float64)
    se = float(deltas.std(ddof=1) / np.sqrt(len(deltas))) if len(deltas) > 1 else 0.0
    by_format = {}
    for case in sorted({row["format_id"] for row in rows}):
        subset = [row for row in rows if row["format_id"] == case]
        by_format[case] = {"states": len(subset),
                           "mean_delta": float(np.mean([row["independent_delta"] for row in subset])),
                           "changed_picks": sum(row["baseline"] != row["selected"] for row in subset),
                           "rows": subset}
    result = {"states": len(rows), "mean_independent_delta": float(deltas.mean()),
            "interval_95": [float(deltas.mean() - 1.96 * se), float(deltas.mean() + 1.96 * se)],
            "better_states": int((deltas > 0).sum()), "worse_states": int((deltas < 0).sum()),
            "by_format": by_format,
            "decision": "INVESTIGATE_ACTION_TRAINING" if deltas.mean() > 0 and
                        by_format["main-c11-t14-r13"]["mean_delta"] > 0 else "REVIEW_ACTION_SEARCH"}
    h2h_rows = [row for row in rows if "independent_h2h_delta" in row]
    if h2h_rows:
        h2h = np.asarray([row["independent_h2h_delta"] for row in h2h_rows], dtype=np.float64)
        h2h_se = float(h2h.std(ddof=1) / np.sqrt(len(h2h))) if len(h2h) > 1 else 0.0
        result["h2h_audited_states"] = len(h2h_rows)
        result["mean_independent_h2h_delta"] = float(h2h.mean())
        result["h2h_interval_95"] = [float(h2h.mean() - 1.96 * h2h_se),
                                     float(h2h.mean() + 1.96 * h2h_se)]
        result["h2h_by_format"] = {case: float(np.mean([row["independent_h2h_delta"]
            for row in h2h_rows if row["format_id"] == case]))
            for case in sorted({row["format_id"] for row in h2h_rows})}
    return result


def run(confirmation=False, confirmation_extra=False, h2h_screen=False):
    cases = {case["id"]: case for case in v83.formats()}
    indices_by_case = (H2H_CASE_INDICES if h2h_screen else EXTRA_CASE_INDICES if confirmation_extra else
                       CONFIRMATION_CASE_INDICES if confirmation else CASE_INDICES)
    split = ("v84_action_h2h_screen" if h2h_screen else "v84_action_confirmation_extra" if confirmation_extra else
             "v84_action_confirmation" if confirmation else "v84_action_audit")
    output = (ROOT / "artifacts/draft_ml/v84-action-h2h-screen" if h2h_screen else
              ROOT / "artifacts/draft_ml/v84-action-confirmation-extra" if confirmation_extra else
              ROOT / "artifacts/draft_ml/v84-action-confirmation" if confirmation else OUTPUT)
    metric = "h2h" if h2h_screen else "utility"
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    jobs = []
    for case, indices in indices_by_case.items():
        for index in indices:
            path = output / "states" / f"{case}-{index:03d}.json"
            if path.exists():
                row = json.loads(path.read_text(encoding="utf-8"))
                if (row.get("format_id"), row.get("state_index"), row.get("screen_metric", "utility")) != (case, index, metric):
                    raise ValueError(f"Incompatible action-audit shard: {path}")
                if len(row.get("independent_delta_samples", [])) != CONFIRM_ROLLOUTS:
                    raise ValueError(f"Incomplete action-audit shard: {path}")
                rows.append(row)
            else:
                jobs.append((cases[case], index, split, metric))
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=v83.configuration()[0]["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(audit_state, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                row = future.result()
                rows.append(row)
                save(output / "states" / f"{row['format_id']}-{row['state_index']:03d}.json", row)
            done = len(jobs) - len(pending)
            save(output / "progress.json", {"completed": len(rows), "total": len(rows) + len(pending),
                 "eta_seconds": (time.monotonic() - started) / done * len(pending) if done else None})
    result = summarize(rows)
    result["split"] = split
    if confirmation_extra:
        first_dir = ROOT / "artifacts/draft_ml/v84-action-confirmation/states"
        first = [json.loads(path.read_text(encoding="utf-8")) for path in first_dir.glob("*.json")]
        if len(first) != sum(map(len, CONFIRMATION_CASE_INDICES.values())):
            raise ValueError("First confirmation is incomplete")
        combined = summarize([*first, *rows])
        combined["passed_confirmation_gate"] = bool(combined["interval_95"][0] > 0 and
            combined["by_format"]["main-c11-t14-r13"]["mean_delta"] > 0 and
            combined["by_format"]["s8-t10-r13"]["mean_delta"] >= 0 and
            result["h2h_interval_95"][0] > 0)
        result["combined"] = combined
        save(output / "combined-summary.json", combined)
    elif confirmation:
        result["passed_confirmation_gate"] = bool(result["interval_95"][0] > 0 and
            result["by_format"]["main-c11-t14-r13"]["mean_delta"] > 0 and
            result["by_format"]["s8-t10-r13"]["mean_delta"] >= 0)
    elif h2h_screen:
        result["passed_h2h_gate"] = bool(result["h2h_interval_95"][0] > 0 and
            result["h2h_by_format"]["main-c11-t14-r13"] > 0 and
            result["h2h_by_format"]["s8-t10-r13"] >= 0)
    save(output / "summary.json", result)
    return result


def resummarize_extra():
    extra_dir = ROOT / "artifacts/draft_ml/v84-action-confirmation-extra"
    first_dir = ROOT / "artifacts/draft_ml/v84-action-confirmation/states"
    extra = [json.loads(path.read_text(encoding="utf-8")) for path in (extra_dir / "states").glob("*.json")]
    first = [json.loads(path.read_text(encoding="utf-8")) for path in first_dir.glob("*.json")]
    expected = sum(map(len, EXTRA_CASE_INDICES.values()))
    if len(extra) != expected or len(first) != expected:
        raise ValueError("Action confirmations are incomplete")
    result = summarize(extra)
    result["split"] = "v84_action_confirmation_extra"
    combined = summarize([*first, *extra])
    combined["passed_confirmation_gate"] = bool(combined["interval_95"][0] > 0 and
        combined["by_format"]["main-c11-t14-r13"]["mean_delta"] > 0 and
        combined["by_format"]["s8-t10-r13"]["mean_delta"] >= 0 and
        result["h2h_interval_95"][0] > 0)
    result["combined"] = combined
    save(extra_dir / "combined-summary.json", combined)
    save(extra_dir / "summary.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirmation", action="store_true")
    parser.add_argument("--confirmation-extra", action="store_true")
    parser.add_argument("--h2h-screen", action="store_true")
    parser.add_argument("--resummarize-extra", action="store_true")
    args = parser.parse_args()
    result = resummarize_extra() if args.resummarize_extra else run(
        args.confirmation, args.confirmation_extra, args.h2h_screen)
    print(json.dumps(result, indent=2), flush=True)
