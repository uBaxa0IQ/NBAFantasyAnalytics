from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from web.backend.services.draft_advisor import lookahead_rerank
from web.backend.services.draft_ml import v8_inference
from web.backend.services.draft_ml.inference import maybe_apply_learned_rerank
from web.backend.services.draft_mock import _strong_profiles, play_mock_draft
from web.backend.services.draft_simulation import _select_player


class FakePolicy:
    def __init__(self):
        self.model = SimpleNamespace(spec={"architecture": "universal_residual_v1"})
        self.path = Path("frozen.pt")

    def predict(self, state, legal=None):
        legal = list(state.legal() if legal is None else legal)
        logits = np.full(len(state.players), -1e9, np.float32)
        for index in legal:
            logits[index] = float(index)
        return logits, np.zeros(14, np.float32)


def _player(player_id, name, pts):
    return {
        "player_id": player_id,
        "name": name,
        "position": "PG",
        "eligible_slots": ["PG", "G", "UT", "BE"],
        "z_scores": {"PTS": pts, "AST": pts / 10},
        "stats": {"GP": 70, "PTS": pts, "AST": pts / 10, "FGM": 4, "FGA": 8, "FTM": 2, "FTA": 2},
        "score": pts,
    }


def _context(players, **overrides):
    payload = dict(
        roster=[],
        remaining=players,
        opponent_rosters=[],
        categories=("PTS", "AST"),
        roster_slots=("PG", "UT"),
        eval_pick=1,
        next_own_pick=4,
        rounds=2,
        team_count=2,
        punt_categories=(),
    )
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_aligned_slots_drop_ir_and_pad_bench():
    assert v8_inference.aligned_slots(("PG", "IR", "BE"), 4) == ("PG", "BE", "BE", "BE")


def test_v8_rerank_orders_by_policy_logits(monkeypatch):
    players = [_player(index, name, 10 - index) for index, name in enumerate(("A", "B", "C", "D"), start=1)]
    monkeypatch.setattr(v8_inference, "v8_checkpoint_path", lambda: Path("frozen.pt"))
    monkeypatch.setattr(v8_inference, "load_v8_policy", lambda: FakePolicy())
    ordered = list(players)
    status = v8_inference.maybe_apply_v8_rerank(ordered, _context(players), limit=4)
    assert status["enabled"] is True
    assert [player["name"] for player in ordered] == ["D", "C", "B", "A"]
    assert ordered[0]["learned_policy_score"] > ordered[-1]["learned_policy_score"]


def test_learned_rerank_falls_back_to_v8_without_sklearn_champion(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAFT_MODEL_CHAMPIONS", str(tmp_path))
    monkeypatch.delenv("DRAFT_MODEL_CHECKPOINT", raising=False)
    monkeypatch.setattr(v8_inference, "v8_checkpoint_path", lambda: Path("frozen.pt"))
    monkeypatch.setattr(v8_inference, "load_v8_policy", lambda: FakePolicy())
    players = [_player(index, name, 10 - index) for index, name in enumerate(("A", "B", "C", "D"), start=1)]
    status = maybe_apply_learned_rerank(list(players), _context(players), limit=4)
    assert status["enabled"] is True
    assert status["policy_type"] == "universal_residual_v1"


def test_select_player_v8_uses_neural_policy(monkeypatch):
    players = [_player(index, name, 10 - index) for index, name in enumerate(("A", "B", "C", "D"), start=1)]
    monkeypatch.setattr(v8_inference, "v8_checkpoint_path", lambda: Path("frozen.pt"))
    monkeypatch.setattr(v8_inference, "load_v8_policy", lambda: FakePolicy())
    selected = _select_player(
        [(float(index), player) for index, player in enumerate(players, start=1)],
        roster=[],
        overall=1,
        own_picks_left=2,
        next_own_pick=4,
        opponent_rosters=[],
        rounds=2,
        team_count=2,
        roster_slots=("PG", "UT"),
        categories=("PTS", "AST"),
        policy_mode="v8",
    )
    assert selected["name"] == "D"


def test_strong_field_samples_v8_slots_from_seed():
    first = _strong_profiles(14, seed=11, human_slot=5)
    again = _strong_profiles(14, seed=11, human_slot=5)
    other = _strong_profiles(14, seed=99, human_slot=5)
    first_v8 = [slot for slot, profile in first.items() if profile["policy"] == "v8"]
    other_v8 = [slot for slot, profile in other.items() if profile["policy"] == "v8"]
    assert first == again
    assert 5 not in first_v8
    assert len(first_v8) == 4
    assert first_v8 != other_v8


def test_two_team_strong_field_stays_adaptive():
    result = play_mock_draft(
        [_player(index, name, 10 - index) for index, name in enumerate(("A", "B", "C", "D"), start=1)],
        slot=1, team_count=2, rounds=2, human_picks=(), seed=1,
        categories=("PTS", "AST"), opponent_field="strong",
    )
    opponent = next(team for team in result["teams"] if not team["is_you"])
    assert opponent["policy"] == "adaptive"


def test_lookahead_does_not_invoke_v8(monkeypatch):
    calls = []

    def fake_simulate(*args, **kwargs):
        calls.append(kwargs.get("own_policy") if "own_policy" in kwargs else args[15])
        return {"average_category_wins": 5.0, "average_league_rank": 2.0, "category_win_samples": [5.0, 5.1]}

    monkeypatch.setattr("web.backend.services.draft_advisor._simulate_slot", fake_simulate)
    players = [_player(index, name, 10 - index) for index, name in enumerate(("A", "B", "C"), start=1)]
    lookahead_rerank(
        players,
        existing_rosters_by_slot={1: [], 2: []},
        slot=1,
        team_count=2,
        rounds=2,
        current_pick=1,
        roster_slots=("PG", "UT"),
        categories=("PTS", "AST"),
        candidate_count=2,
        runs=2,
    )
    assert calls
    assert set(calls) == {"adaptive_heuristic"}


@pytest.mark.skipif(not v8_inference.DEFAULT_CHECKPOINT.exists(), reason="v811 frozen.pt is not present")
def test_real_v811_checkpoint_selects_a_legal_player():
    players = [
        _player(index, f"P{index}", 20 - index)
        for index in range(1, 17)
    ]
    status = v8_inference.maybe_apply_v8_rerank(list(players), _context(
        players, team_count=8, rounds=2, next_own_pick=16, roster_slots=("PG", "UT") * 1,
    ), limit=8)
    assert status["enabled"] is True
    assert status["checkpoint"] == "frozen.pt"
