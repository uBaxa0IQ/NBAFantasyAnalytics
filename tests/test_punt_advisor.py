from core.config import CATEGORIES
from web.backend.services.punt_advisor import analyze_punt_strategies


def _scores(default=0.0):
    return {category: default for category in CATEGORIES}


def _player(name, overrides=None):
    z_scores = _scores()
    z_scores.update(overrides or {})
    return {"name": name, "z_scores": z_scores}


def test_analyzer_evaluates_every_viable_punt_depth():
    team_scores = {team_id: _scores() for team_id in range(1, 5)}
    roster = [_player(f"Player {index}") for index in range(8)]

    result = analyze_punt_strategies(team_scores, 1, roster)

    assert [item["punt_count"] for item in result["strategies_by_depth"]] == [0, 1, 2, 3, 4, 5]
    assert result["total_combinations"] == 1024
    assert all(
        len(item["best"]["punt_categories"]) == item["punt_count"]
        for item in result["strategies_by_depth"]
    )


def test_more_punts_strengthen_core_but_reduce_margin_for_error():
    team_scores = {team_id: _scores() for team_id in range(1, 5)}
    for team_id in (2, 3, 4):
        team_scores[team_id]["BLK"] = 3.0
        team_scores[team_id]["A/TO"] = 3.0
    roster = [
        _player(f"Player {index}", {"BLK": -1.0, "A/TO": -1.0})
        for index in range(8)
    ]

    result = analyze_punt_strategies(team_scores, 1, roster)
    baseline = result["strategies_by_depth"][0]["best"]
    double_punt = result["strategies_by_depth"][2]["best"]

    assert set(double_punt["punt_categories"]) == {"BLK", "A/TO"}
    assert double_punt["core_control"] > baseline["core_control"]
    assert double_punt["margin_for_error"] == baseline["margin_for_error"] - 2


def test_recommendation_never_automatically_punts_five_categories():
    team_scores = {team_id: _scores() for team_id in range(1, 5)}
    roster = [_player(f"Player {index}") for index in range(8)]

    result = analyze_punt_strategies(team_scores, 1, roster)

    assert result["recommendation"]["punt_count"] <= 4
