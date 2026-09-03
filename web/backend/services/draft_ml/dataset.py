"""Streaming JSONL dataset storage with deterministic scenario-level splits."""

from __future__ import annotations

import gzip
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path


def split_for_scenario(scenario_id):
    bucket = int(hashlib.sha256(str(scenario_id).encode("utf-8")).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


@contextmanager
def dataset_writer(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    mode = "wt"
    with opener(path, mode, encoding="utf-8") as handle:
        def write(record):
            payload = dict(record)
            payload.setdefault("split", split_for_scenario(payload["scenario_id"]))
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        yield write


def read_records(path, split=None):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if split is None or record.get("split") == split:
                yield record


def dataset_summary(path):
    counts = {"train": 0, "validation": 0, "test": 0, "total": 0}
    states = set()
    for record in read_records(path):
        split = record.get("split", "train")
        counts[split] = counts.get(split, 0) + 1
        counts["total"] += 1
        states.add(record.get("state_id"))
    counts["states"] = len(states)
    return counts

