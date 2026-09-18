"""V8.2.5: higher-precision reliability gate on genuine ESPN 2027 projections."""
from __future__ import annotations

import argparse
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
from scripts import draft_v81_multiformat as v81
from scripts import draft_v82_auto_strategy as v82
from scripts import draft_v824_label_audit as audit
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save

CONFIG = ROOT / "configs/draft_ml_v825_precision.json"
BASE_FINGERPRINT = audit.fingerprint


def fingerprint():
    digest = hashlib.sha256(BASE_FINGERPRINT().encode())
    digest.update(Path(__file__).read_bytes())
    return digest.hexdigest()


def initialize():
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    v81.initialize(str(ROOT / settings["champion"]))
    config, inherited, _, policies = v81.CTX
    snapshot = json.loads((ROOT / settings["snapshot"]).read_text(encoding="utf-8"))
    if snapshot.get("season") != 2027 or snapshot.get("period") != "2027_projected":
        raise ValueError("V8.2.5 requires the frozen 2027 projected snapshot")
    if snapshot.get("previous_season_fallback") is not False:
        raise ValueError("Fallback-contaminated snapshot is forbidden")
    v81.CTX = config, inherited, snapshot, policies
    v81.PLAYER_CACHE = {}
    v82.CTX = {"settings": settings, "strategy": None}
    audit.CTX = {"settings": settings}


def configure():
    audit.CONFIG = CONFIG
    audit.fingerprint = fingerprint
    audit.initialize = initialize


def plan():
    prepared = audit.plan()
    prepared["experiment"] = "V8.2.5 ESPN 2027 projected precision audit"
    prepared["hours"] = {"generation": [10, 24], "analysis": [.02, .1], "total": [10, 24]}
    prepared["snapshot"] = str(ROOT / json.loads(CONFIG.read_text(encoding="utf-8"))["snapshot"])
    return prepared


def run():
    prepared = plan()
    expected = fingerprint()
    _, out = audit.configuration()
    out.mkdir(parents=True, exist_ok=True)
    with lock(out / "run.lock"):
        journal_path = out / "run-state.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {
            "provenance": expected, "completed": [],
        }
        if journal["provenance"] != expected:
            raise ValueError("Incompatible V8.2.5 resume")
        save(out / "plan.json", prepared)

        def status(name, error=None):
            save(out / "status.json", {"pid": os.getpid(), "phase": name,
                "completed": len(journal["completed"]), "total": 2, "provenance": expected,
                "error": error, "updated_at": time.time(), "training": False})

        child = None
        try:
            for stage in ("generate", "analyze"):
                if stage in journal["completed"]:
                    continue
                status("RUNNING:" + stage)
                with (out / f"{stage}.log").open("a", encoding="utf-8") as handle:
                    child = subprocess.Popen([sys.executable, "-u", str(Path(__file__)),
                        "--stage", stage, "--provenance", expected], cwd=ROOT,
                        stdout=handle, stderr=subprocess.STDOUT)
                    while child.poll() is None:
                        try:
                            child.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            status("RUNNING:" + stage)
                if child.returncode:
                    raise RuntimeError(f"{stage} failed; progress retained")
                journal["completed"].append(stage)
                save(journal_path, journal)
            status("COMPLETE")
        except BaseException as exc:
            if child is not None and child.poll() is None:
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
            status("FAILED", "".join(traceback.format_exception_only(type(exc), exc)).strip())
            raise


if __name__ == "__main__":
    configure()
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stage", choices=("generate", "analyze"))
    parser.add_argument("--provenance")
    args = parser.parse_args()
    if args.stage:
        initialize()
        audit.phase(args.stage, args.provenance)
    elif args.execute:
        run()
    else:
        print(json.dumps(plan(), indent=2))
