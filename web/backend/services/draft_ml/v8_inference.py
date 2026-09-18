"""On-the-clock UniversalPolicy inference. Never call from Monte Carlo/lookahead."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from ..draft_simulation import DEFAULT_DRAFT_SLOTS, _slot_at_pick
from .v8_state import UniversalState, normalize_categories, normalize_slot


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CHECKPOINT = ROOT / "artifacts/draft_ml/v811-residual/frozen.pt"

_policy = None
_policy_key = None
_policy_lock = Lock()


def _identity(player):
    return player.get("player_id") if player.get("player_id") is not None else player.get("name")


def v8_checkpoint_path():
    if os.getenv("DRAFT_DISABLE_LEARNED") == "1" or os.getenv("DRAFT_DISABLE_V8") == "1":
        return None
    override = os.getenv("DRAFT_V8_CHECKPOINT")
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            return path
        if os.getenv("DRAFT_ML_STRICT") == "1":
            raise FileNotFoundError(f"Requested V8 checkpoint missing: {path}")
        return None
    return DEFAULT_CHECKPOINT if DEFAULT_CHECKPOINT.exists() else None


def load_v8_policy():
    global _policy, _policy_key
    path = v8_checkpoint_path()
    if path is None:
        return None
    key = str(path.resolve())
    with _policy_lock:
        if _policy is None or _policy_key != key:
            from .v8_network import UniversalPolicy
            _policy = UniversalPolicy(path, device="cpu")
            _policy_key = key
        return _policy


def aligned_slots(roster_slots, rounds):
    slots = []
    for slot in roster_slots or DEFAULT_DRAFT_SLOTS:
        value = normalize_slot(slot)
        if value in {"IR", "", "ROOKIE"}:
            continue
        slots.append(value)
    if not slots:
        slots = ["BE"] * max(1, int(rounds))
    while len(slots) < rounds:
        slots.append("BE")
    return tuple(slots[:rounds])


def _collect_players(context):
    players = []
    index_by_id = {}

    def add(player):
        if not player:
            return
        identity = _identity(player)
        if identity is None or identity in index_by_id:
            return
        index_by_id[identity] = len(players)
        players.append(player)

    for player in context.remaining or ():
        add(player)
    for player in context.roster or ():
        add(player)
    for roster in context.opponent_rosters or ():
        for player in roster:
            add(player)
    return players, index_by_id


def _pad_players(players, index_by_id, needed):
    while len(players) < needed:
        name = f"_v8_pad_{len(players)}"
        pad = {
            "player_id": name,
            "name": name,
            "position": "UT",
            "eligible_slots": ["UT", "BE"],
            "z_scores": {},
            "stats": {},
        }
        index_by_id[name] = len(players)
        players.append(pad)
    return players, index_by_id


def state_from_context(context):
    """Build a UniversalState that matches the live/mock board."""
    team_count = max(2, int(getattr(context, "team_count", 2) or 2))
    rounds = max(1, int(getattr(context, "rounds", 1) or 1))
    pick = max(1, int(getattr(context, "eval_pick", 1) or 1))
    categories = normalize_categories(getattr(context, "categories", ()) or ("PTS",))
    players, index_by_id = _collect_players(context)
    players, index_by_id = _pad_players(players, index_by_id, team_count * rounds)
    state = UniversalState(
        players,
        aligned_slots(getattr(context, "roster_slots", ()), rounds),
        team_count,
        rounds=rounds,
        categories=categories,
    )
    state.pick = min(pick, team_count * rounds + 1)
    current_slot = _slot_at_pick(min(pick, team_count * rounds), team_count)
    drafted = []
    for player in context.roster or ():
        identity = _identity(player)
        if identity in index_by_id:
            drafted.append((current_slot, index_by_id[identity]))
    other_slots = [slot for slot in range(1, team_count + 1) if slot != current_slot]
    for slot, roster in zip(other_slots, context.opponent_rosters or ()):
        for player in roster:
            identity = _identity(player)
            if identity in index_by_id:
                drafted.append((slot, index_by_id[identity]))
    remaining_ids = {_identity(player) for player in context.remaining or ()}
    owned = {index for _, index in drafted}
    state.rosters = {slot: [] for slot in range(1, team_count + 1)}
    state.drafted_at = state.drafted_at.copy()
    for order, (slot, index) in enumerate(drafted, start=1):
        if index in state.rosters[slot]:
            continue
        state.rosters[slot].append(index)
        state.drafted_at[index] = min(order, max(1, pick - 1))
    state.remaining = [
        index for index, player in enumerate(players)
        if _identity(player) in remaining_ids and index not in owned
    ]
    return state, index_by_id


def maybe_apply_v8_rerank(players, context, limit=16):
    if os.getenv("DRAFT_DISABLE_LEARNED") == "1" or os.getenv("DRAFT_DISABLE_V8") == "1":
        return {"enabled": False, "reason": "disabled"}
    if len(players) < 2:
        return {"enabled": False, "reason": "insufficient_candidates"}
    path = v8_checkpoint_path()
    if path is None:
        return {"enabled": False, "reason": "no_checkpoint"}
    try:
        policy = load_v8_policy()
        if policy is None:
            return {"enabled": False, "reason": "no_checkpoint"}
        state, index_by_id = state_from_context(context)
        candidate_limit = max(2, min(int(limit or len(players)), len(players)))
        legal = []
        candidates = []
        for player in players[:candidate_limit]:
            identity = _identity(player)
            index = index_by_id.get(identity)
            if index is None or index not in state.remaining:
                continue
            legal.append(index)
            candidates.append(player)
        if len(candidates) < 2:
            return {"enabled": False, "reason": "insufficient_legal"}
        logits, _ = policy.predict(state, legal=legal)
        ranked = sorted(
            zip(candidates, legal),
            key=lambda item: float(logits[item[1]]),
            reverse=True,
        )
        ordered = [player for player, _ in ranked]
        by_identity = {
            _identity(player): round(float(logits[index]), 4)
            for player, index in ranked
        }
        candidate_ids = {id(player) for player in ordered}
        score_floor = max(
            (float(player.get("score", 0.0)) for player in players if id(player) not in candidate_ids),
            default=-100.0,
        )
        for index, player in enumerate(ordered):
            player["learned_policy_score"] = by_identity[_identity(player)]
            player["score"] = round(score_floor + (len(ordered) - index) * 0.10, 4)
        players[:] = ordered + [player for player in players if id(player) not in candidate_ids]
        architecture = getattr(getattr(policy, "model", None), "spec", {}) or {}
        return {
            "enabled": True,
            "checkpoint": path.name,
            "model_version": "v811-residual",
            "policy_type": architecture.get("architecture") or "universal_v8",
            "uses_market_features": False,
        }
    except ImportError:
        return {"enabled": False, "reason": "torch_unavailable"}
    except Exception as error:
        if os.getenv("DRAFT_ML_STRICT") == "1":
            raise
        return {"enabled": False, "reason": "checkpoint_error", "detail": str(error)}


def select_v8_player(candidates, context):
    if not candidates:
        return None
    ranked = list(candidates)
    status = maybe_apply_v8_rerank(ranked, context, limit=len(ranked))
    if not status.get("enabled"):
        return None
    return ranked[0]
