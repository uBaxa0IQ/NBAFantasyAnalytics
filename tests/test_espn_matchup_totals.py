from types import SimpleNamespace

from core.league_metadata import LeagueMetadata


def test_matchup_totals_follow_espn_scoreboard_not_raw_player_stats():
    home = SimpleNamespace(team_id=1, team_name='Home')
    away = SimpleNamespace(team_id=2, team_name='Away')
    player = SimpleNamespace(
        name='Player', playerId=42, position='PG', slot_position='BE',
        stats={'0': {'total': {'PTS': 91, 'FGM': 40, 'FGA': 80}}},
    )
    box = SimpleNamespace(
        home_team=home, away_team=away, home_lineup=[player], away_lineup=[],
        home_stats={'PTS': {'value': 0, 'result': 'TIE'},
                    'FGM': {'value': 0}, 'FGA': {'value': 0},
                    'FG%': {'value': 0}},
        away_stats={'PTS': {'value': 0}},
    )
    metadata = LeagueMetadata()
    metadata.league = SimpleNamespace()
    metadata.teams = [home, away]
    metadata._get_box_scores_cached = lambda week: [box]

    current = metadata.get_matchup_box_score(1, 1)
    assert current['totals']['PTS'] == 0
    assert current['totals']['FGM'] == 0
    assert metadata.get_all_teams_stats_for_week(1)[1]['stats']['PTS'] == 0

    box.home_stats['PTS']['value'] = 55
    box.home_stats['FGM']['value'] = 20
    box.home_stats['FGA']['value'] = 40
    box.home_stats['FG%']['value'] = 0.5
    updated = metadata.get_matchup_box_score(1, 1)
    assert updated['totals']['PTS'] == 55
    assert updated['totals']['FGM'] == 20
    assert updated['totals']['FGA'] == 40
    assert updated['totals']['FG%'] == 0.5
