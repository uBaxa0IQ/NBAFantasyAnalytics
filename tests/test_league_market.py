from copy import deepcopy
from types import SimpleNamespace

import pytest

from web.backend.services.espn_market import (
    _serialize_player, apply_league_market, blended_market_pick,
    clear_espn_market_cache, get_espn_market,
)
from web.backend.services.draft_benchmark import _rank_value, prepare_benchmark_market


def player():
    return {"player_id": 1, "name": "A", "espn_roto_rank": 80,
            "espn_adp": 70, "espn_league_rater_rank": 10,
            "espn_rater_categories": ["PTS", "REB"],
            "stats": {"PTS": 20, "REB": 10}, "position": "C"}


def test_league_rank_drives_market_and_opponent_without_overwriting_draft_rank():
    row = player()
    apply_league_market([row], ["REB", "PTS"])
    assert row["espn_roto_rank"] == 80
    assert row["espn_market_pick"] == 16
    assert _rank_value(row, "espn_roto_rank") == 10
    assert row["market_category_match"] is True


def test_category_switch_does_not_leak_previous_league_market():
    row = player()
    apply_league_market([row], ["REB", "PTS"])
    apply_league_market([row], ["AST", "PTS"])
    assert row["market_roto_rank"] == 80
    assert row["market_category_match"] is False
    assert row["espn_market_pick"] == blended_market_pick(70, 80)


def test_late_season_rater_cannot_make_early_draft_player_safe_to_wait():
    row = {**player(), "espn_league_rater_rank": 185, "espn_roto_rank": 15, "espn_adp": 5}
    apply_league_market([row], ["PTS", "REB"])
    assert row["market_roto_rank"] == 15
    assert row["espn_market_pick"] <= blended_market_pick(5, 15)


@pytest.mark.parametrize("bad", [None, 0, -1, float("nan"), float("inf"), True, "1"])
def test_invalid_rater_rank_falls_back(bad):
    row = {**player(), "espn_league_rater_rank": bad}
    apply_league_market([row], ["PTS", "REB"])
    assert row["market_roto_rank"] == 80


def test_explicit_benchmark_markets_are_isolated():
    original = [player()]
    before = deepcopy(original)
    league = prepare_benchmark_market(original, ["PTS", "REB"], "league_rater")
    draft = prepare_benchmark_market(league, ["PTS", "REB"], "espn_draft")
    assert _rank_value(league[0], "espn_roto_rank") == 10
    assert _rank_value(draft[0], "espn_roto_rank") == 80
    assert original == before
    with pytest.raises(ValueError, match="category mismatch"):
        prepare_benchmark_market(original, ["PTS"], "league_rater")


def test_parser_keeps_rater_and_draft_as_distinct_sources():
    row = _serialize_player({"player": {"id": 1, "fullName": "A",
        "draftRanksByRankType": {"ROTO": {"rank": 80}}},
        "ratings": {"0": {"totalRanking": 10, "totalRating": 8.5}}})
    assert row["espn_league_rater_rank"] == 10
    assert row["espn_league_rater_value"] == 8.5
    assert row["espn_roto_rank"] == 80


def test_market_cache_invalidates_on_category_change():
    clear_espn_market_cache()
    calls = []
    def fetch(**kwargs):
        calls.append(kwargs)
        return {"players": [{"player": {"id": 1, "fullName": "A"},
                             "ratings": {"0": {"totalRanking": 10}}}]}
    meta = SimpleNamespace(league_id=1, year=2027, categories=["PTS"],
        league=SimpleNamespace(espn_request=SimpleNamespace(league_get=fetch)))
    first = get_espn_market(meta)
    meta.categories = ["REB"]
    second = get_espn_market(meta)
    assert len(calls) == 2
    assert first["players"][0]["espn_rater_categories"] == ["PTS"]
    assert second["players"][0]["espn_rater_categories"] == ["REB"]
    clear_espn_market_cache()
