"""Transfer check: next-pick choices against projected league-specific ROTO opponents.

The first three rounds and the selected action come from the action H2H audit.
Only future opponent behaviour changes. This is an exploratory stress test, not
a sealed holdout and not an official ESPN league-specific Player Rater feed.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v83_distributional as v83
from scripts.draft_v84_action_audit import summarize
from scripts.run_v74_resilient import resilient_json as save

SOURCE = ROOT / "artifacts/draft_ml/v84-action-h2h-screen/states"
OUTPUT = ROOT / "artifacts/draft_ml/v84-opponent-robustness"
ROLLOUTS = 16
TERMINAL_DRAWS = 4


def choose_roto(state, noise):
    categories = state.categories
    return max(state.legal(), key=lambda index: (
        sum(float(state.players[index].get("z_scores", {}).get(category, 0.0))
            for category in categories) + noise[index], -index))


def outcome_samples(state, hero, action, key):
    branch = state.clone()
    branch.apply(action)
    category_count = len(state.categories)
    utilities = []
    h2h = []
    for rollout in range(ROLLOUTS):
        future = branch.clone()
        rng = random.Random(f"{key}:roto:{rollout}")
        noise = [rng.gauss(0.0, 0.5) for _ in future.players]
        while not future.complete:
            if future.slot == hero:
                pick = v81.network_order(future, v81.CTX[3]["v81"])[0][0]
            else:
                pick = choose_roto(future, noise)
            future.apply(pick)
        draws = np.stack([future.targets(hero, f"{key}:roto:{rollout}:draw:{draw}", .12, .08)
                          for draw in range(TERMINAL_DRAWS)])
        utilities.append(float(np.mean([v83.outcome_utility(row, category_count) for row in draws])))
        h2h.append(float(np.mean(draws[:, category_count + 3] + .5 * draws[:, category_count + 4])))
    return np.asarray(utilities), np.asarray(h2h)


def worker(source):
    case, index, split, baseline_name, selected_name = source
    state, hero, _, key = v82.starting_state(case, index, split)
    available = {state.players[player]["name"]: player for player in state.legal()}
    baseline = available[baseline_name]
    selected = available[selected_name]
    old_utility, old_h2h = outcome_samples(state, hero, baseline, key)
    if baseline == selected:
        new_utility, new_h2h = old_utility, old_h2h
    else:
        new_utility, new_h2h = outcome_samples(state, hero, selected, key)
    return {"format_id": case["id"], "seat": hero, "state_index": index,
            "baseline": baseline_name, "selected": selected_name,
            "independent_delta": float(np.mean(new_utility - old_utility)),
            "independent_delta_samples": (new_utility - old_utility).tolist(),
            "independent_h2h_delta": float(np.mean(new_h2h - old_h2h)),
            "independent_h2h_delta_samples": (new_h2h - old_h2h).tolist()}


def main():
    cases = {case["id"]: case for case in v83.formats()}
    case = cases["main-c11-t14-r13"]
    rows = []
    jobs = []
    for path in sorted(SOURCE.glob("main-c11-t14-r13-*.json")):
        source = json.loads(path.read_text(encoding="utf-8"))
        index = int(source["state_index"])
        destination = OUTPUT / "states" / path.name
        if destination.exists():
            row = json.loads(destination.read_text(encoding="utf-8"))
            if row["state_index"] != index or len(row["independent_h2h_delta_samples"]) != ROLLOUTS:
                raise ValueError(f"Incompatible robustness shard: {destination}")
            rows.append(row)
        else:
            jobs.append((case, index, "v84_action_h2h_screen", source["baseline"], source["selected"]))
    if len(rows) + len(jobs) != 14:
        raise ValueError("Expected 14 completed source scenarios")
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=v83.configuration()[0]["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(worker, job) for job in jobs}
        while pending:
            ready, pending = wait(pending, timeout=15, return_when=FIRST_COMPLETED)
            for future in ready:
                row = future.result()
                rows.append(row)
                save(OUTPUT / "states" / f"{row['format_id']}-{row['state_index']:03d}.json", row)
            done = len(jobs) - len(pending)
            save(OUTPUT / "progress.json", {"completed": len(rows), "total": 14,
                "eta_seconds": (time.monotonic() - started) / done * len(pending) if done else None})
    result = summarize(rows)
    result["opponents"] = "projected_11cat_roto_with_fixed_player_noise"
    result["decision"] = "TRANSFER_SIGNAL" if result["h2h_interval_95"][0] > 0 else "TRANSFER_UNPROVEN"
    save(OUTPUT / "summary.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "by_format"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
