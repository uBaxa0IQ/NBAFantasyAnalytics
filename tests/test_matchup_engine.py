from datetime import datetime, timezone
import sqlite3

import pytest

from core.matchup_mc import aggregate_stats, simulate_matchup_odds
from core.player_rates import availability_probability, build_player_rate
from core.season_mc import simulate_playoff_title, simulate_season
from web.backend.services.forecast_history import connect, record


def player(name, pts, *, p_play=1.0, position="PG"):
    mean = {
        "PTS": pts, "REB": pts / 4, "AST": pts / 5, "STL": 1, "BLK": .5,
        "TO": 2, "FGM": pts / 2.5, "FGA": pts, "FTM": 3, "FTA": 4,
        "3PM": 2, "3PA": 5, "DD": .1,
    }
    return {
        "player_id": name, "name": name, "position": position,
        "eligible_slots": [position, "UT"], "schedule": {"1": {}, "2": {}},
        "z_scores": {"PTS": pts}, "stats": mean, "p_play": p_play,
        "rate": {"mean": mean, "std": {key: max(.2, value * .15) for key, value in mean.items()}, "p_play": p_play},
    }


def test_rate_blend_is_shrunk_and_injury_prior_is_explicit():
    base = {"player_id": 1, "name": "A", "stats": {"PTS": 20}, "injured": True, "injury_status": "QUESTIONABLE"}
    rate = build_player_rate(base, {"PTS": 20, "GP": 40}, {"PTS": 30, "GP": 10}, {"PTS": 24})
    assert 20 < rate.mean["PTS"] < 30
    assert rate.std["PTS"] > 0
    assert rate.p_play == pytest.approx(.40)
    assert availability_probability({**base, "lineup_slot": "IR"}) == 0


def test_aggregation_uses_attempt_weighted_percentages():
    stats = aggregate_stats({"FGM": 1, "FGA": 2}, {"FGM": 9, "FGA": 18})
    assert stats["FG%"] == pytest.approx(.5)


def test_matchup_mc_is_seeded_bounded_and_favors_stronger_team():
    strong = [player("strong", 34)]
    weak = [player("weak", 8)]
    args = dict(categories=["PTS", "REB", "AST", "FG%", "FT%", "TO"], reverse_categories=["TO"], slots=("PG",), trials=300, seed=42)
    first = simulate_matchup_odds(strong, weak, [1, 2], **args)
    second = simulate_matchup_odds(strong, weak, [1, 2], **args)
    assert first == second
    assert first["p_win"] > .80
    assert first["p_win"] + first["p_tie"] + first["p_loss"] == pytest.approx(1)
    assert sum(first["score_distribution"].values()) == pytest.approx(1)
    for category in first["categories"].values():
        assert category["p_win"] + category["p_tie"] + category["p_loss"] == pytest.approx(1)


def test_out_player_can_return_on_documented_date():
    returning = player("returning", 30, p_play=0.0)
    returning["expected_return_date"] = "2030-01-02"
    returning["schedule"] = {
        "1": {"date": datetime(2030, 1, 1, tzinfo=timezone.utc)},
        "2": {"date": datetime(2030, 1, 2, tzinfo=timezone.utc)},
    }
    weak = [player("weak", 1)]
    result = simulate_matchup_odds([returning], weak, [1, 2], categories=["PTS"], slots=("PG",), trials=100, seed=7)
    assert result["p_win"] > .9


def test_season_mc_returns_seed_distribution_and_playoff_probabilities():
    teams = [
        {"team_id": 1, "team_name": "A", "wins": 5},
        {"team_id": 2, "team_name": "B", "wins": 5},
        {"team_id": 3, "team_name": "C", "wins": 1},
        {"team_id": 4, "team_name": "D", "wins": 1},
    ]
    odds = [
        {"team1_id": 1, "team2_id": 2, "p_win": .7, "p_tie": 0, "p_loss": .3},
        {"team1_id": 3, "team2_id": 4, "p_win": .5, "p_tie": 0, "p_loss": .5},
    ]
    result = simulate_season(teams, odds, 2, trials=300, seed=9)
    assert all(sum(row["p_seed"].values()) == pytest.approx(1) for row in result)
    assert sum(row["p_playoff"] for row in result) == pytest.approx(2)
    assert result[0]["team_id"] in {1, 2}


def test_forecast_database_migrates_legacy_schema(tmp_path, monkeypatch):
    path = tmp_path / "forecast.db"
    monkeypatch.setenv("FORECAST_DB", str(path))
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE forecasts (league INTEGER, season INTEGER, week INTEGER, team1 INTEGER, team2 INTEGER, period TEXT, categories TEXT, reverse_cats TEXT, prediction TEXT, actual TEXT, created TEXT, PRIMARY KEY(league,season,week,team1,team2,period))")
    with connect() as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(forecasts)")}
    assert {"p_win", "p_tie", "p_loss", "engine_version", "seed", "trials"} <= columns
    record(1, 2030, 2, 1, 2, "total", {"PTS": 10}, {"PTS": 8}, ["PTS"], [], {
        "p_win": .7, "p_tie": .1, "p_loss": .2, "engine_version": "test", "seed": 3, "trials": 100,
    })
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT p_win,engine_version FROM forecasts").fetchone() == (.7, "test")


def test_playoff_title_mc_handles_six_team_bracket_and_byes():
    seeds = [{"team_id": team_id, "seed": team_id} for team_id in range(1, 7)]
    probabilities = {}
    for left in range(1, 7):
        for right in range(1, 7):
            if left != right:
                probabilities[(left, right)] = .8 if left < right else .2
    result = simulate_playoff_title(seeds, probabilities, trials=1000, seed=12)
    assert sum(result.values()) == pytest.approx(1)
    assert result[1] > result[6]
