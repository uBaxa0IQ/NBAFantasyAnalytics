from core.simulation import simulate_all_vs_all


def test_all_vs_all_returns_details_for_both_sides():
    teams = {
        1: {"name": "A", "stats": {"PTS": 10, "REB": 4}},
        2: {"name": "B", "stats": {"PTS": 8, "REB": 6}},
        3: {"name": "C", "stats": {"PTS": 7, "REB": 3}},
    }

    results = simulate_all_vs_all(teams, categories=("PTS", "REB"))
    by_id = {result["team_id"]: result for result in results}

    assert by_id[1]["wins"] == 1
    assert by_id[1]["ties"] == 1
    assert len(by_id[1]["matchups"]) == 2
    versus_b = next(matchup for matchup in by_id[1]["matchups"] if matchup["opponent_id"] == 2)
    assert versus_b["result"] == "tie"
    assert versus_b["categories"] == {"PTS": "win", "REB": "loss"}
