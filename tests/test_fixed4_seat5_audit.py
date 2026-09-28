from scripts.audit_fixed4_seat5_2027 import interval, settings, strategies


def test_fixed_four_punts_and_reproducible_board():
    config = settings()
    assert len(config["punt_categories"]) == 4
    assert config["team_count"] == 14
    assert config["rounds"] == 13
    assert config["hero_seat"] == 5
    assert config["user_board"][1] == "Josh Giddey"
    assert strategies(config)[0]["targets"] == config["user_board"]


def test_paired_interval_does_not_claim_precision_for_one_run():
    result = interval([0.25])
    assert result == {"n": 1, "mean": 0.25, "ci95": [0.25, 0.25]}
