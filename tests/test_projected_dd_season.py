from types import SimpleNamespace

import pytest

import core.league_metadata as metadata_module
from core.config import PERIODS
from core.league_metadata import LeagueMetadata
from core.projected_dd import estimate_projected_double_doubles, normalize_projected_stats
from core.projection import project_team_stats
from core.z_score import calculate_z_scores


def _player(player_id, name, *, dd=None, rebounds=10):
    projection = {
        "GP": 70, "PTS": 20, "REB": rebounds, "AST": 4,
        "FGM": 7, "FGA": 14, "FTM": 4, "FTA": 6,
        "STL": 1, "BLK": 1, "3PM": 2, "3PA": 5, "TO": 2,
        "FG%": .5, "FT%": 4 / 6, "3PT%": .4, "A/TO": 2,
    }
    if dd is not None:
        projection["DD"] = dd
    return SimpleNamespace(
        playerId=player_id, name=name, position="C", eligibleSlots=["C"],
        stats={
            PERIODS["projected"]: {"avg": projection},
            PERIODS["total"]: {"avg": {"PTS": 18, "DD": .3}},
        },
    )


def test_season_projected_dd_uses_draft_estimator_without_changing_z_population(monkeypatch):
    own = _player(1, "Own", rebounds=11)
    opponent = _player(2, "Opponent", dd=.2, rebounds=7)
    free_agent = _player(3, "Free agent", rebounds=9)
    metadata = LeagueMetadata(year=int(PERIODS["projected"].split("_")[0]))
    metadata.teams = [
        SimpleNamespace(team_id=1, team_name="Mine", roster=[own]),
        SimpleNamespace(team_id=2, team_name="Other", roster=[opponent]),
    ]
    monkeypatch.setattr(metadata, "get_free_agents", lambda size=300: [free_agent])
    historical = {
        1: {"GP": 65, "PTS": 19, "REB": 10, "AST": 4, "STL": 1, "BLK": 1, "DD": .55},
        3: {"GP": 66, "PTS": 20, "REB": 9, "AST": 4, "STL": 1, "BLK": 1, "DD": .35},
    }
    monkeypatch.setattr(metadata_module, "previous_season_stats", lambda meta, ids: historical)

    projected = {
        player.playerId: normalize_projected_stats(player.stats[PERIODS["projected"]]["avg"])
        for player in (own, opponent, free_agent)
    }
    expected, _ = estimate_projected_double_doubles(projected, historical)
    rows = metadata.get_all_players_stats(PERIODS["projected"], "avg")

    assert len(rows) == 2  # Free agents inform DD, but not the season Z baseline.
    assert rows[0]["stats"]["DD"] == pytest.approx(expected[1]["DD"])
    assert rows[1]["stats"]["DD"] == .2  # ESPN's explicit value takes precedence.
    assert metadata.get_player_stats(free_agent, PERIODS["projected"], "avg")["DD"] == pytest.approx(expected[3]["DD"])
    assert metadata.get_player_stats(own, PERIODS["total"], "avg")["DD"] == .3

    scored = calculate_z_scores(metadata, PERIODS["projected"])
    assert "DD" in scored["league_metrics"]
    assert all("DD" in player["z_scores"] for player in scored["players"])
    matchup = project_team_stats(rows, {"Own": 4, "Opponent": 3})
    assert matchup["DD"] == pytest.approx(expected[1]["DD"] * 4 + .2 * 3)
