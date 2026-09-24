from web.backend.services.draft_mock import MockDraftError, play_mock_draft


def _player(player_id, name, adp, pts, ast=1, fgm=4, fga=8):
    return {
        "player_id": player_id,
        "name": name,
        "position": "PG",
        "eligible_slots": ["PG", "G", "UT"],
        "espn_adp": adp,
        "espn_roto_rank": adp,
        "espn_market_pick": float(adp),
        "total_z": 10 - adp,
        "z_scores": {"PTS": pts, "AST": ast},
        "stats": {"GP": 70, "PTS": pts, "AST": ast, "FGM": fgm, "FGA": fga, "FTM": 2, "FTA": 2},
        "games_played": 70,
    }


PLAYERS = [
    _player(1, "Alpha", 1, 30),
    _player(2, "Beta", 2, 24),
    _player(3, "Gamma", 3, 18),
    _player(4, "Delta", 4, 12),
]


def test_empty_queue_stops_on_the_clock_for_slot_one():
    result = play_mock_draft(PLAYERS, slot=1, team_count=2, rounds=2, human_picks=(), seed=1, categories=("PTS", "AST"))
    assert result["status"] == "on_the_clock"
    assert result["overall"] == 1
    assert result["available"][0]["player_id"] == 1
    assert result["your_roster"] == []
    assert result["model_pick"]["player_id"] in {1, 2, 3, 4}
    assert result["round_reports"] == []


def test_human_pick_then_adp_fills_until_next_turn():
    result = play_mock_draft(
        PLAYERS, slot=1, team_count=2, rounds=2, human_picks=(3,), seed=1, categories=("PTS", "AST"),
    )
    assert result["status"] == "on_the_clock"
    assert result["overall"] == 4
    assert [row["player"]["name"] for row in result["pick_log"]] == ["Gamma", "Alpha", "Beta"]
    assert result["your_roster"][0]["name"] == "Gamma"
    assert result["available"][0]["name"] == "Delta"
    assert result["round_reports"][0]["round"] == 1
    assert result["standings"][0]["league_rank"] == 1


def test_complete_mock_returns_league_table():
    result = play_mock_draft(
        PLAYERS, slot=1, team_count=2, rounds=2, human_picks=(3, 4), seed=1, categories=("PTS", "AST"),
    )
    assert result["status"] == "complete"
    assert result["league_rank"] in (1, 2)
    assert len(result["standings"]) == 2
    assert [report["round"] for report in result["round_reports"]] == [1, 2]
    you = next(row for row in result["standings"] if row["is_you"])
    assert [player["name"] for player in you["roster"]] == ["Gamma", "Delta"]
    assert you["category_ranks"]["PTS"] == 2
    assert you["matchup_wins"] + you["matchup_ties"] + you["matchup_losses"] == 1
    assert result["standings"] == sorted(
        result["standings"],
        key=lambda row: (-(row["matchup_wins"] + 0.5 * row["matchup_ties"]), -row["category_wins"], row["slot"]),
    )


def test_league_table_ranks_by_h2h_matchups_not_average_cats():
    from web.backend.services.draft_mock import _league_table

    def roster(pts, reb, ast):
        return [{"stats": {"GP": 1, "PTS": pts, "REB": reb, "AST": ast}, "z_scores": {}, "name": "x", "player_id": 1}]

    profiles = {slot: {"policy": "model", "punts": ()} for slot in (1, 2, 3, 4)}
    standings = _league_table(
        {
            1: roster(10, 10, 1),
            2: roster(9, 9, 100),
            3: roster(1, 1, 50),
            4: roster(1, 1, 50),
        },
        profiles,
        1,
        {1: "A", 2: "B", 3: "C", 4: "D"},
        ("PTS", "REB", "AST"),
    )
    by_slot = {row["slot"]: row for row in standings}
    assert by_slot[1]["matchup_wins"] == 3
    assert by_slot[2]["matchup_wins"] == 2
    assert by_slot[2]["category_wins"] > by_slot[1]["category_wins"]
    assert [row["slot"] for row in standings][:2] == [1, 2]
    assert by_slot[1]["league_rank"] == 1
    assert by_slot[2]["league_rank"] == 2


def test_taken_player_is_rejected():
    opening = play_mock_draft(
        PLAYERS, slot=2, team_count=2, rounds=2, human_picks=(), seed=1, categories=("PTS", "AST"),
    )
    taken_id = opening["pick_log"][0]["player"]["player_id"]
    try:
        play_mock_draft(
            PLAYERS, slot=2, team_count=2, rounds=2, human_picks=(taken_id,), seed=1, categories=("PTS", "AST"),
        )
    except MockDraftError as error:
        assert "недоступен" in str(error)
    else:
        raise AssertionError("expected MockDraftError")


def test_heuristic_advisor_follows_fixed_punts():
    players = [
        _player(1, "Scorer", 1, 30, ast=0),
        _player(2, "Passer", 2, 0, ast=30),
        _player(3, "Gamma", 3, 8, ast=8),
        _player(4, "Delta", 4, 4, ast=4),
    ]
    punted = play_mock_draft(
        players, slot=1, team_count=2, rounds=2, human_picks=(), seed=1,
        categories=("PTS", "AST"), advisor="heuristic", punt_categories=("PTS",),
    )
    balanced = play_mock_draft(
        players, slot=1, team_count=2, rounds=2, human_picks=(), seed=1,
        categories=("PTS", "AST"), advisor="heuristic", punt_categories=(),
    )
    assert punted["advisor"] == "heuristic"
    assert punted["advisor_label"] == "Эвристика · punt PTS"
    assert punted["model_pick"]["name"] == "Passer"
    assert punted["model_pick"]["total_z"] == 30
    scorer = next(player for player in punted["available"] if player["name"] == "Scorer")
    assert scorer["total_z"] == 0
    assert scorer["general_z"] == 30
    assert balanced["model_pick"]["name"] == "Scorer"


def test_v8_advisor_is_selected_without_using_punts():
    result = play_mock_draft(
        PLAYERS, slot=1, team_count=2, rounds=2, human_picks=(), seed=1,
        categories=("PTS", "AST"), advisor="v8", punt_categories=("PTS",),
    )
    assert result["advisor"] == "v8"
    assert result["advisor_label"] == "Нейросеть V8"
    assert result["model_pick"]["player_id"] in {1, 2, 3, 4}


def test_strong_field_marks_opponents_as_adaptive():
    result = play_mock_draft(
        PLAYERS, slot=1, team_count=2, rounds=2, human_picks=(), seed=1,
        categories=("PTS", "AST"), opponent_field="strong",
    )
    opponent = next(team for team in result["teams"] if not team["is_you"])
    assert opponent["policy"] == "adaptive"
