"""Resume the frozen V8.2.1 run after the Path-only checksum bug.

This recovery layer deliberately leaves the experiment source, configuration,
checkpoints, seeds and provenance unchanged.  It only normalizes checkpoint
paths before hashing and resumes after the completed training stage.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import draft_v821_auto_strategy as experiment
from scripts.draft_ml_v7_run import lock
from scripts.run_v74_resilient import resilient_json as save
from web.backend.services.draft_ml.v7_state import sha as path_sha


EXPECTED_PROVENANCE = "b4a70e74453a14229079c91d4c6a5c7cb6d1c10845f611c5595891e33d416324"


def compatible_sha(path):
    """Accept the string checkpoint paths produced by V8.2.1 evaluate()."""
    return path_sha(Path(path))


def main():
    actual = experiment.fingerprint()
    if actual != EXPECTED_PROVENANCE:
        raise ValueError(
            f"Frozen V8.2.1 experiment changed ({actual}); refusing recovery"
        )

    _, output = experiment.configuration()
    journal_path = output / "run-state.json"
    status_path = output / "status.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    previous_status = json.loads(status_path.read_text(encoding="utf-8"))
    if journal.get("provenance") != EXPECTED_PROVENANCE:
        raise ValueError("Saved run provenance does not match frozen V8.2.1")
    if journal.get("completed") != ["train"]:
        raise ValueError(
            f"Expected completed training only, got {journal.get('completed')}"
        )

    settings, _ = experiment.configuration()
    checkpoints = [
        output / "training" / f"seed-{seed}" / "best.pt"
        for seed in settings["training_seeds"]
    ]
    missing = [str(path) for path in checkpoints if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing trained checkpoints: {missing}")

    # The only runtime behavior changed by this recovery entry point.
    experiment.sha = compatible_sha

    with lock(output / "run.lock"):
        audit_path = output / f"checksum-recovery-{time.time_ns()}.json"
        save(
            audit_path,
            {
                "experiment_provenance": EXPECTED_PROVENANCE,
                "wrapper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "previous_status": previous_status,
                "checkpoint_sha256": [path_sha(path) for path in checkpoints],
                "change": "Normalize checkpoint strings to Path before SHA-256; no model or evaluation change.",
                "started_at": time.time(),
            },
        )

        def set_status(phase, error=None):
            save(
                status_path,
                {
                    "pid": os.getpid(),
                    "phase": phase,
                    "completed": len(journal["completed"]),
                    "total": 3,
                    "provenance": EXPECTED_PROVENANCE,
                    "error": error,
                    "updated_at": time.time(),
                    "training": False,
                    "recovery": "checksum-path-only",
                },
            )

        try:
            set_status("RUNNING:validation")
            experiment.phase("validation", EXPECTED_PROVENANCE)
            journal["completed"].append("validation")
            save(journal_path, journal)

            selection = json.loads((output / "selection.json").read_text(encoding="utf-8"))
            if not selection["passed"]:
                set_status("STOP_FOR_REVIEW")
                return

            set_status("RUNNING:holdout")
            experiment.phase("holdout", EXPECTED_PROVENANCE)
            journal["completed"].append("holdout")
            save(journal_path, journal)
            set_status("COMPLETE")
        except BaseException as exc:
            set_status(
                "FAILED",
                "".join(traceback.format_exception_only(type(exc), exc)).strip(),
            )
            raise


if __name__ == "__main__":
    main()
