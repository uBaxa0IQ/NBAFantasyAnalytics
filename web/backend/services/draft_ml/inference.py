"""Optional learned reranker. It is inert until a champion is promoted."""

from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import fmean, pstdev

from ..draft_strategy import strategy_probabilities
from .features import extract_candidate_features
from .model import DraftModelBundle


_bundle_cache = {}


def _champion_path(categories):
    override = os.getenv("DRAFT_MODEL_CHECKPOINT")
    if override:
        path = Path(override)
        return path if path.exists() else None
    root = Path(os.getenv("DRAFT_MODEL_CHAMPIONS", "artifacts/draft_ml/champions"))
    configured = set(categories)
    standard = {'FG%', 'FT%', '3PM', 'REB', 'AST', 'STL', 'BLK', 'PTS'}
    custom = standard | {'3PT%', 'DD', 'A/TO'}
    if configured not in (standard, custom):
        return None
    format_name = 'custom11' if configured == custom else 'standard8'
    format_root = root / format_name
    pointer = format_root / "current.json"
    if not pointer.exists():
        return None
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    path = format_root / payload["name"]
    return path if path.exists() else None


def _bundle(path):
    key = str(path.resolve())
    if key not in _bundle_cache:
        _bundle_cache.clear()
        _bundle_cache[key] = DraftModelBundle(path)
    return _bundle_cache[key]


def maybe_apply_learned_rerank(players, context, limit=16):
    checkpoint = _champion_path(context.categories)
    if checkpoint is None or len(players) < 2:
        return {"enabled": False, "reason": "no_promoted_checkpoint"}
    try:
        strategies = strategy_probabilities(
            context.roster, context.categories, context.rounds,
            fixed_punts=context.punt_categories,
        )
        candidates = list(players[:limit])
        records = [{
            "candidate_id": candidate.get("player_id") or candidate.get("name"),
            "candidate_name": candidate.get("name"),
            "features": extract_candidate_features(
                roster=context.roster,
                remaining=context.remaining,
                candidate=candidate,
                opponent_rosters=context.opponent_rosters,
                categories=context.categories,
                roster_slots=context.roster_slots,
                overall_pick=context.eval_pick,
                next_own_pick=context.next_own_pick,
                rounds=context.rounds,
                team_count=context.team_count,
                strategy_rows=strategies,
            ),
        } for candidate in candidates]
        predictions = _bundle(checkpoint).predict(records)
        rewards = [row["reward"] for row in predictions]
        mean, scale = fmean(rewards), pstdev(rewards) or 1.0
        by_identity = {
            row["candidate_id"]: (row["reward"] - mean) / scale * 0.72 + row["policy_probability"] * 0.28
            for row in predictions
        }
        candidates.sort(
            key=lambda player: by_identity[player.get("player_id") or player.get("name")],
            reverse=True,
        )
        candidate_ids = {id(player) for player in candidates}
        score_floor = max(
            (float(player.get("score", 0.0)) for player in players if id(player) not in candidate_ids),
            default=-100.0,
        )
        for index, player in enumerate(candidates):
            player["learned_policy_score"] = round(
                by_identity[player.get("player_id") or player.get("name")], 4,
            )
            player["score"] = round(score_floor + (len(candidates) - index) * 0.10, 4)
        players[:] = candidates + [player for player in players if id(player) not in candidate_ids]
        bundle = _bundle(checkpoint)
        return {
            "enabled": True,
            "checkpoint": checkpoint.name,
            "model_version": bundle.manifest.get("model_version"),
        }
    except Exception as error:
        return {"enabled": False, "reason": "checkpoint_error", "detail": str(error)}
