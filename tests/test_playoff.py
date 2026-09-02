from types import SimpleNamespace

from core.playoff import (
    advance_title_contenders,
    build_seeds,
    classify_bracket,
    get_matchup_bracket_type,
    get_playoff_context,
    get_round_name,
)


def test_playoff_context_uses_matchup_period_configuration():
    settings = SimpleNamespace(
        reg_season_count=16,
        matchup_periods={str(i): [i] for i in range(1, 19)} | {"19": [19, 20]},
        playoff_team_count=8,
        playoff_seed_tie_rule="H2H_RECORD",
    )
    league = SimpleNamespace(
        currentMatchupPeriod=19,
        scoringPeriodId=140,
        finalScoringPeriod=146,
        settings=settings,
    )

    context = get_playoff_context(league)

    assert context["playoff_start_week"] == 17
    assert context["playoff_periods"] == [17, 18, 19]
    assert context["round"] == 3
    assert context["round_name"] == "Финал"
    assert context["is_playoff"] is True
    assert context["phase"] == "playoffs"


def test_completed_season_is_not_reported_as_active_playoffs():
    settings = SimpleNamespace(
        reg_season_count=16,
        matchup_periods={"16": [16], "17": [17], "18": [18], "19": [19, 20]},
        playoff_team_count=8,
        playoff_seed_tie_rule="H2H_RECORD",
    )
    league = SimpleNamespace(
        currentMatchupPeriod=19,
        scoringPeriodId=175,
        finalScoringPeriod=146,
        settings=settings,
    )

    context = get_playoff_context(league)

    assert context["is_playoff_period"] is True
    assert context["is_playoff"] is False
    assert context["season_complete"] is True
    assert context["phase"] == "complete"


def test_seed_comes_from_espn_standing_not_win_percentage():
    teams = [
        SimpleNamespace(team_id=1, team_name="A", standing=2, wins=12, losses=4, ties=0),
        SimpleNamespace(team_id=2, team_name="B", standing=1, wins=11, losses=5, ties=0),
    ]

    seeds = build_seeds(teams)

    assert [seed["team_id"] for seed in seeds] == [2, 1]
    assert [seed["seed"] for seed in seeds] == [1, 2]


def test_bracket_requires_both_teams_in_playoff_field():
    assert classify_bracket(1, 8, 8) == "championship"
    assert classify_bracket(1, 9, 8) == "consolation"
    assert classify_bracket(None, 2, 8) == "consolation"


def test_title_path_advances_only_winners():
    matchups = [
        {"team1_id": 1, "team2_id": 8, "winner": "HOME"},
        {"team1_id": 4, "team2_id": 5, "winner": "AWAY"},
        {"team1_id": 9, "team2_id": 10, "winner": "HOME"},
    ]
    contenders = advance_title_contenders(set(range(1, 9)), matchups)

    assert contenders == {1, 5}
    assert get_matchup_bracket_type(1, 5, 1, 5, 8, contenders) == "championship"
    assert get_matchup_bracket_type(4, 8, 4, 8, 8, contenders) == "placement"
    assert get_matchup_bracket_type(9, 10, 9, 10, 8, contenders) == "consolation"


def test_round_names_scale_with_field_size():
    assert get_round_name(1, 8) == "Четвертьфинал"
    assert get_round_name(2, 8) == "Полуфинал"
    assert get_round_name(3, 8) == "Финал"
