from types import SimpleNamespace

from web.backend.services import projections


def test_weekly_projection_uses_only_official_pairs(monkeypatch):
    teams = [SimpleNamespace(team_id=team_id) for team_id in (1, 2, 3, 4)]
    league = SimpleNamespace(currentMatchupPeriod=1)
    stats = {
        1: {"name": "A", "stats": {"PTS": 100, "TO": 10}},
        2: {"name": "B", "stats": {"PTS": 90, "TO": 8}},
        3: {"name": "C", "stats": {"PTS": 95, "TO": 12}},
        4: {"name": "D", "stats": {"PTS": 110, "TO": 9}},
    }
    metadata = SimpleNamespace(
        league=league,
        get_teams=lambda: teams,
        get_categories=lambda: ["PTS", "TO"],
        reverse_categories={"TO"},
        get_matchup_box_score=lambda week, team_id: None,
        get_schedule_matchups=lambda start, end: [
            {"team1_id": 1, "team2_id": 3},
            {"team1_id": 2, "team2_id": 4},
        ],
    )
    monkeypatch.setattr(projections, "get_remaining_scoring_periods", lambda league, week: [1, 2])
    monkeypatch.setattr(projections, "build_league_snapshot", lambda metadata, period: object())
    monkeypatch.setattr(
        projections, "project_snapshot_for_matchup",
        lambda snapshot, teams, days, **kwargs: (stats, {}),
    )

    result = projections.project_scheduled_matchups(metadata, "2027_projected", 1)

    assert result["scoring_periods"] == [1, 2]
    assert [(row["team1_id"], row["team2_id"]) for row in result["matchups"]] == [(1, 3), (2, 4)]
    assert (result["matchups"][0]["team1_wins"], result["matchups"][0]["team2_wins"]) == (2, 0)
    assert result["matchups"][0]["categories"][1]["winner"] == "win"
