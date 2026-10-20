from datetime import datetime, timezone
from types import SimpleNamespace

from core.projection import (
    build_matchup_lineups,
    get_matchup_scoring_periods,
    get_remaining_scoring_periods,
    optimize_daily_lineup,
    project_team_stats,
)


def make_player(name, position, value, schedule, stats=None, eligible=None):
    return {
        "name": name,
        "position": position,
        "eligible_slots": eligible or [position, "UT"],
        "z_scores": {"PTS": value},
        "schedule": {str(period): {} for period in schedule},
        "stats": stats or {},
        "available": True,
    }


def test_daily_optimizer_respects_position_slots():
    players = [
        make_player("PG star", "PG", 5, [1]),
        make_player("PG backup", "PG", 4, [1]),
        make_player("C", "C", 3, [1]),
    ]

    result = optimize_daily_lineup(players, slots=("PG", "C"))

    assert [item["player"]["name"] for item in result["starters"]] == ["PG star", "C"]
    assert [player["name"] for player in result["bench"]] == ["PG backup"]


def test_daily_optimizer_fills_slots_before_comparing_value():
    players = [
        make_player("Positive", "PG", 2, [1]),
        make_player("Negative", "C", -3, [1]),
    ]

    result = optimize_daily_lineup(players, slots=("PG", "C"))

    assert [item["player"]["name"] for item in result["starters"]] == ["Positive", "Negative"]


def test_matchup_lineup_counts_only_selected_game_days():
    players = [
        make_player("A", "PG", 2, [1, 2]),
        make_player("B", "PG", 1, [1, 2]),
    ]

    result = build_matchup_lineups(players, [1, 2], slots=("PG",))

    assert result["selected_games"] == {"A": 2, "B": 0}
    assert len(result["days"]) == 2


def test_projection_uses_attempt_weighted_percentages():
    players = [
        make_player("Volume", "PG", 2, [1], {"PTS": 20, "FGM": 10, "FGA": 20}),
        make_player("Efficient", "C", 2, [1], {"PTS": 10, "FGM": 4, "FGA": 5}),
    ]

    projection = project_team_stats(players, {"Volume": 2, "Efficient": 1})

    assert projection["PTS"] == 50
    assert projection["FGM"] == 24
    assert projection["FGA"] == 45
    assert projection["FG%"] == 24 / 45


def test_remaining_periods_use_espn_scoring_period_mapping():
    league = SimpleNamespace(current_week=135, matchup_ids={19: ["133", "134", "135", "136"]})

    assert get_remaining_scoring_periods(league, 19) == [135, 136]


def test_matchup_expands_espn_week_settings_to_daily_scoring_periods():
    opening_tipoff = int(datetime(2026, 10, 20, 23, tzinfo=timezone.utc).timestamp() * 1000)
    league = SimpleNamespace(
        matchup_ids={1: ["1"]},
        settings=SimpleNamespace(matchup_periods={"1": [1], "2": [2], "19": [19, 20]}),
        firstScoringPeriod=1,
        finalScoringPeriod=146,
        scoringPeriodId=4,
        pro_schedule={1: {"1": [{"date": opening_tipoff}]}},
    )

    assert get_matchup_scoring_periods(league, 1) == list(range(1, 7))
    assert get_remaining_scoring_periods(league, 1) == list(range(4, 7))
    assert get_matchup_scoring_periods(league, 2) == list(range(7, 14))
    assert get_matchup_scoring_periods(league, 19) == list(range(126, 140))
    league.matchup_ids[2] = ["2"]
    assert get_matchup_scoring_periods(league, 2) == list(range(7, 14))
