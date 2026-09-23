from web.backend.services.draft_constructor import (
    evaluate_constructor_roster,
    normalize_roster_ids,
    simulate_assembly,
)


def _player(player_id, name, adp, **stats):
    base = {"GP": 70, "PTS": 10, "REB": 5, "AST": 3, "STL": 1, "BLK": 1, "FGM": 4, "FGA": 8, "FTM": 2, "FTA": 3, "TO": 1.5, "DD": 0.2}
    base.update(stats)
    return {
        "player_id": player_id,
        "name": name,
        "position": "C",
        "espn_market_pick": float(adp),
        "espn_adp": float(adp),
        "espn_roto_rank": adp,
        "z_scores": {"REB": 1},
        "stats": base,
    }


def test_normalize_roster_ids_drops_duplicates_and_pads():
    assert normalize_roster_ids([1, 1, 2, None], 5) == [1, None, 2, None, None]


def test_constructor_totals_use_season_volume():
    players = [
        _player(1, "A", 8, REB=10, AST=5, FGM=6, FGA=10, TO=2, BLK=2, STL=1.5, DD=0.4),
        _player(2, "B", 24, REB=8, AST=4, FGM=4, FGA=8, TO=1, BLK=1, STL=1, DD=0.2),
    ]
    result = evaluate_constructor_roster(players, [1, 2], slot=1, team_count=2, rounds=2, runs=20)
    assert result["filled"] == 2
    assert abs(result["totals"]["REB"] - (10 * 70 + 8 * 70)) < 1e-6
    assert abs(result["totals"]["FG%"] - round(10 / 18, 4)) < 1e-9
    reb = next(row for row in result["categories"] if row["category"] == "REB")
    assert reb["band"] == "below"
    assert reb["working"] is True
    partial = evaluate_constructor_roster(players, [1, 2], slot=5, team_count=14, rounds=13, runs=20)
    assert next(row for row in partial["categories"] if row["category"] == "REB")["band"] == "building"


def test_early_adp_survives_first_pick_and_dies_late():
    players = [_player(index, f"P{index}", index, REB=5) for index in range(1, 21)]
    early = simulate_assembly(players, [1, None], slot=1, team_count=4, rounds=2, runs=40)
    late = simulate_assembly(players, [None, 1], slot=1, team_count=4, rounds=2, runs=40)
    assert early["slots"][0]["available"] == 100.0
    assert late["slots"][1]["available"] < 20.0
    assert late["full_rate"] < 20.0
    assert early["core_rate"] == 100.0
