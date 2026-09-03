"""Objective model promotion gate; never replaces a champion implicitly."""

from __future__ import annotations

import json
from pathlib import Path
import shutil


DEFAULT_THRESHOLDS = {
    "reward_mae_max": 0.55,
    "policy_top1_min": 0.35,
    "policy_regret_max": 0.20,
    "self_play_ci_lower_min": 0.0,
    "worst_decile_drop_max": 0.05,
}


def promotion_decision(test_metrics, self_play_report, thresholds=None):
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    adaptive = next(row for row in self_play_report["strategies"] if row["id"] == "adaptive")
    champion = next(row for row in self_play_report["strategies"] if row["id"] == "legacy_balanced")
    comparison = next(
        row for row in self_play_report["comparisons_to_legacy_balanced"]
        if row["strategy"] == "adaptive"
    )
    checks = {
        "reward_mae": test_metrics["value"]["reward"]["mae"] <= thresholds["reward_mae_max"],
        "policy_top1": test_metrics["policy"]["top1_accuracy"] >= thresholds["policy_top1_min"],
        "policy_regret": test_metrics["policy"]["mean_regret"] <= thresholds["policy_regret_max"],
        "self_play_ci": comparison["delta_category_wins_ci95"][0] > thresholds["self_play_ci_lower_min"],
        "downside": adaptive["worst_decile_category_wins"] + thresholds["worst_decile_drop_max"] >= champion["worst_decile_category_wins"],
    }
    return {"approved": all(checks.values()), "checks": checks, "thresholds": thresholds}


def promote_checkpoint(checkpoint_dir, champions_dir, decision, name, format_name):
    if not decision.get("approved"):
        raise ValueError("Promotion gate rejected this checkpoint")
    source = Path(checkpoint_dir)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    trained_format = manifest.get("metadata", {}).get("format")
    if trained_format and trained_format != format_name:
        raise ValueError(f"Checkpoint format {trained_format} does not match {format_name}")
    format_root = Path(champions_dir) / format_name
    destination = format_root / name
    if destination.exists():
        raise FileExistsError(f"Champion version already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    (destination / "promotion.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    # Pointer update is explicit and atomic; old version directories remain recoverable.
    pointer = format_root / "current.json"
    temporary = pointer.with_suffix(".tmp")
    temporary.write_text(json.dumps({"name": name}, indent=2), encoding="utf-8")
    temporary.replace(pointer)
    return destination
