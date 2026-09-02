from types import SimpleNamespace

from core.config import CATEGORIES, DEFAULT_CATEGORIES, REVERSE_CATEGORIES
from core.league_metadata import LeagueMetadata
from core.z_score import calculate_z_scores_from_players


def test_standard_nine_cat_is_read_from_espn_and_turnovers_are_reversed():
    original_categories = list(CATEGORIES)
    original_reverse = set(REVERSE_CATEGORIES)
    metadata = LeagueMetadata()
    scoring_items = [
        {"statId": stat_id, "isReverseItem": stat_id == 11}
        for stat_id in (0, 6, 3, 2, 1, 17, 19, 20, 11)
    ]
    metadata.league = SimpleNamespace(
        espn_request=SimpleNamespace(get_league=lambda: {
            "settings": {"scoringSettings": {
                "scoringType": "H2H_CATEGORY",
                "scoringItems": scoring_items,
            }}
        })
    )

    try:
        metadata._configure_scoring()
        assert metadata.categories == ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO']
        assert metadata.reverse_categories == {'TO'}

        players = [
            {"name": "Careful", "position": "PG", "team_id": 1, "team_name": "A", "stats": {"PTS": 10, "TO": 1}},
            {"name": "Sloppy", "position": "PG", "team_id": 2, "team_name": "B", "stats": {"PTS": 10, "TO": 5}},
        ]
        result = calculate_z_scores_from_players(players, categories=['PTS', 'TO'], reverse_categories={'TO'})
        assert result["players"][0]["z_scores"]["TO"] > 0
        assert result["players"][1]["z_scores"]["TO"] < 0
    finally:
        CATEGORIES[:] = original_categories or DEFAULT_CATEGORIES
        REVERSE_CATEGORIES.clear()
        REVERSE_CATEGORIES.update(original_reverse)


def test_inactive_percentage_category_in_player_stats_is_ignored():
    players = [
        {
            "name": "Player A",
            "position": "PG",
            "team_id": 1,
            "team_name": "A",
            "stats": {
                "PTS": 20, "FG%": 0.50, "FGA": 10, "FGM": 5,
                "FT%": 0.80, "FTA": 5, "FTM": 4,
                "3PT%": 0.40, "3PA": 5, "3PM": 2,
            },
        },
        {
            "name": "Player B",
            "position": "SG",
            "team_id": 2,
            "team_name": "B",
            "stats": {
                "PTS": 10, "FG%": 0.40, "FGA": 10, "FGM": 4,
                "FT%": 0.60, "FTA": 5, "FTM": 3,
                "3PT%": 0.30, "3PA": 5, "3PM": 1.5,
            },
        },
    ]

    result = calculate_z_scores_from_players(
        players,
        categories=['PTS', 'FG%', 'FT%'],
    )

    assert set(result['league_metrics']) == {'PTS', 'FG%', 'FT%'}
    for player in result['players']:
        assert '3PT%' not in player['z_scores']
