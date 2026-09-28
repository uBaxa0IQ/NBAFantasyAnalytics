"""Paired H2H audit of the frozen rollout actor in the exact target league."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from scripts import draft_v81_multiformat as v81
from scripts import draft_v83_distributional as v83
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v8_state import UniversalState

OUTPUT = ROOT / "artifacts/draft_ml/v84-candidate-audit/actor-h2h.json"


def episode(index):
    case = v83.configuration()[0]["target_format"]
    players = v81.case_players(case)
    hero = index % case["team_count"] + 1
    key = f"v84:actor:{case['id']}:{index}"
    opponents = v81.opponent_assignments(case, key)
    results = {}
    for mode in ("heuristic", "v81"):
        state = UniversalState(players, case["slots"], case["team_count"],
                               categories=case["categories"], reverse_categories=case.get("reverse", ()))
        while not state.complete:
            if state.slot != hero:
                action = v81.heuristic_action(state, opponents[state.slot]["weights"], key,
                                             opponents[state.slot])
            elif mode == "heuristic":
                action = v81.heuristic_action(state, dict.fromkeys(case["categories"], 1.0), key + ":hero")
            else:
                action = v81.network_order(state, v81.CTX[3]["v81"])[0][0]
            state.apply(action)
        results[mode] = np.mean([state.targets(hero, f"{key}:draw:{draw}", .12, .08)
                                 for draw in range(4)], axis=0).tolist()
    return {"episode": index, "seat": hero, "categories": case["categories"],
            "team_count": case["team_count"], "results": results}


def run(cycles=2):
    settings, _ = v83.configuration()
    total = settings["target_format"]["team_count"] * cycles
    rows = []
    with ProcessPoolExecutor(max_workers=settings["workers"], initializer=v83.initialize) as pool:
        pending = {pool.submit(episode, index) for index in range(total)}
        for future in as_completed(pending):
            row = future.result()
            rows.append(row)
            print(f"{len(rows)}/{total}", flush=True)
    rows.sort(key=lambda row: row["episode"])
    result = {"format_id": settings["target_format"]["id"], "drafts": total,
              "v81_vs_heuristic": v81.metric(rows, "v81", "heuristic"), "rows": rows}
    save(OUTPUT, result)
    return result


if __name__ == "__main__":
    result = run()
    print(json.dumps({"output": str(OUTPUT), "drafts": result["drafts"],
                      "v81_vs_heuristic": result["v81_vs_heuristic"]}, indent=2))
