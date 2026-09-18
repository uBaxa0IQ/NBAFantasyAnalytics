"""I/O-only recovery entry point for the frozen V7.4 experiment.

Keep the experiment source and its provenance unchanged. This operational layer
changes only JSON persistence; no policy, seeds, settings or evaluation changes.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import draft_v74_late_search as experiment


def resilient_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    # Close the handle before replace. Never delete the destination to unlock it.
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        for attempt in range(21):
            try:
                os.replace(temp, path)
                return
            except PermissionError:
                if attempt == 20:
                    raise
                time.sleep(min(.05 * (attempt + 1), .5))
    except PermissionError:
        # Progress display is not experiment data. A blocked heartbeat must not
        # cancel expensive workers; next heartbeat retries with current counters.
        if path.name == 'status.json' and payload.get('phase') == 'RUNNING':
            print('WARNING: status heartbeat temporarily blocked; computation continues.', file=sys.stderr, flush=True)
            try:
                temp.unlink()
            except OSError:
                pass
            return
        # Preserve the temp file for recovery if a result or final status cannot
        # be committed. Unlike a heartbeat, this failure must not be ignored.
        raise


def main():
    config = json.loads((ROOT / 'configs/draft_ml_v7.json').read_text())
    expected = experiment.provenance(config)
    saved = json.loads((experiment.OUTPUT / 'status.json').read_text())
    if saved['provenance'] != expected:
        raise ValueError('Frozen experiment changed; refusing I/O-only resume')
    experiment.atomic_json = resilient_json
    # Unique audit record, preserving the original failure and all result files.
    audit = experiment.OUTPUT / ('io-recovery-' + str(time.time_ns()) + '.json')
    resilient_json(audit, dict(experiment_provenance=expected,
        wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        previous_status=saved, change='Retry atomic JSON replacement; nonfatal RUNNING heartbeat only.',
        started_at=time.time()))
    experiment.run()


if __name__ == '__main__':
    main()
