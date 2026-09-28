import pytest

from web.backend.services import draft_benchmark as benchmark
from web.backend.services.draft_ml.inference import maybe_apply_learned_rerank
from types import SimpleNamespace


@pytest.mark.parametrize("policy, expected", [
    ("adaptive_heuristic", "adaptive_heuristic"), ("adaptive", "adaptive"), ("model", "legacy"),
])
def test_hero_dispatch_calls_actual_requested_optimizer(monkeypatch, policy, expected):
    calls = []
    def selector(market_order, *args, **kwargs):
        calls.append(kwargs["policy_mode"])
        return market_order[-1][1]
    monkeypatch.setattr(benchmark, "_select_player", selector)
    players = [
        {"player_id": i, "name": str(i), "position": "PG", "espn_roto_rank": i, "z_scores": {"PTS": i}}
        for i in (1, 2)
    ]
    result = benchmark._draft_once(
        players, 1, 2, 1, {"policy": policy, "punts": ()}, {1: 1, 2: 2}, {1: 1, 2: 2},
        roster_slots=(), categories=("PTS",), include_roster=True,
    )
    assert calls == [expected]
    assert result["roster"][0]["player_id"] == 2  # ROTO would pick 1.


def test_unknown_hero_policy_fails_instead_of_becoming_roto():
    with pytest.raises(ValueError, match="Unknown draft policy"):
        benchmark._draft_once([], 1, 2, 1, {"policy": "typo"}, {}, {})


def test_opponent_rank_noise_changes_who_survives_to_hero_pick():
    players = [
        {"player_id": 1, "name": "A", "position": "PG", "espn_roto_rank": 1,
         "espn_adp": 1, "stats": {"GP": 70, "PTS": 10}},
        {"player_id": 2, "name": "B", "position": "PG", "espn_roto_rank": 2,
         "espn_adp": 2, "stats": {"GP": 70, "PTS": 9}},
    ]
    strategy = {"policy": "roto", "punts": ()}
    market = {1: 1.0, 2: 2.0}
    first = benchmark._draft_once(players, 2, 2, 1, strategy, market,
                                  {1: 1.0, 2: 2.0}, roster_slots=(),
                                  categories=("PTS",), include_roster=True)
    flipped = benchmark._draft_once(players, 2, 2, 1, strategy, market,
                                    {1: 2.0, 2: 1.0}, roster_slots=(),
                                    categories=("PTS",), include_roster=True)
    assert first["roster"][0]["name"] == "B"
    assert flipped["roster"][0]["name"] == "A"


def test_board_targets_available_player_and_falls_back_when_taken(monkeypatch):
    players = [
        {"player_id": 1, "name": "A", "position": "PG", "espn_roto_rank": 1,
         "espn_adp": 1, "stats": {"GP": 70, "PTS": 10}},
        {"player_id": 2, "name": "B", "position": "PG", "espn_roto_rank": 2,
         "espn_adp": 2, "stats": {"GP": 70, "PTS": 9}},
    ]
    calls = []
    def fallback(market_order, *args, **kwargs):
        calls.append(kwargs["policy_mode"])
        return market_order[0][1]
    monkeypatch.setattr(benchmark, "_select_player", fallback)
    strategy = {"policy": "board", "punts": ("PTS",), "targets": ["B"]}
    available = benchmark._draft_once(players, 1, 2, 1, strategy,
                                      {1: 1.0, 2: 2.0}, {1: 1.0, 2: 2.0},
                                      roster_slots=(), categories=("PTS",), include_roster=True)
    assert available["roster"][0]["name"] == "B"
    assert not calls
    taken = benchmark._draft_once(players, 2, 2, 1, strategy,
                                  {1: 1.0, 2: 2.0}, {1: 2.0, 2: 1.0},
                                  roster_slots=(), categories=("PTS",), include_roster=True)
    assert taken["roster"][0]["name"] == "A"
    assert calls == ["adaptive_heuristic"]


def test_category_market_does_not_overwrite_official_roto(monkeypatch):
    players = [{"player_id": 1, "total_z": 1, "espn_roto_rank": 1},
               {"player_id": 2, "total_z": 5, "espn_roto_rank": 2}]
    monkeypatch.setattr(benchmark, "prepare_players_for_categories", lambda p, c: [dict(x) for x in p])
    result = benchmark.prepare_benchmark_market(players, ("PTS",), "category_z")
    assert result[1]["benchmark_roto_rank"] == 1
    assert result[1]["espn_roto_rank"] == 2
    assert "benchmark_roto_rank" not in players[1]


def test_disable_learned_overrides_even_an_existing_champion(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAFT_DISABLE_LEARNED", "1")
    monkeypatch.setenv("DRAFT_MODEL_CHECKPOINT", str(tmp_path))
    result = maybe_apply_learned_rerank([{}, {}], SimpleNamespace(categories=("PTS",)))
    assert result["enabled"] is False
