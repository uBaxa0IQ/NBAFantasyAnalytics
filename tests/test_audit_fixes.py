from datetime import datetime, timedelta
from itertools import product
from random import Random
from types import SimpleNamespace

import pytest

from core.projection import optimize_daily_lineup, can_play_slot, build_matchup_lineups
from core.simulation import compare_category_stats
from core.roster_rules import league_slots
from core.matchup_value import combine_stats, matchup_utility
from core.trade_roster import selected_names_after_trade
from web.backend.services import punt_advisor


def test_turnovers_and_custom_reverse_direction():
    assert compare_category_stats({'TO': 2}, {'TO': 10}, ['TO'], {'TO'})['team1_wins'] == 1
    assert compare_category_stats({'PTS': 2}, {'PTS': 10}, ['PTS'], {'PTS'})['team1_wins'] == 1


@pytest.mark.parametrize('fill_slots', [True, False])
def test_assignment_matches_exhaustive_search(fill_slots):
    rng = Random(7)
    slots = ('PG', 'G', 'C')
    for _ in range(30):
        players = [{'name': str(i), 'position': rng.choice(['PG', 'SG', 'C']), 'z_scores': {'PTS': rng.randint(-5, 8)}} for i in range(4)]
        best = None
        for assignments in product(range(-1, len(players)), repeat=len(slots)):
            indices = [i for i in assignments if i >= 0]
            if len(set(indices)) != len(indices):
                continue
            if any(i >= 0 and not can_play_slot(players[i], slot) for i, slot in zip(assignments, slots)):
                continue
            value = sum(players[i]['z_scores']['PTS'] for i in indices)
            key = (len(indices), value) if fill_slots else (value,)
            best = max(best, key) if best is not None else key
        result = optimize_daily_lineup(players, slots, fill_slots=fill_slots)
        actual = (len(result['starters']), result['total_value']) if fill_slots else (result['total_value'],)
        assert actual == best


def test_actual_slots_and_composite_positions():
    metadata = SimpleNamespace(league=SimpleNamespace(settings=SimpleNamespace(position_slot_counts={'PG': 1, 'C': 2, 'BE': 3, 'IR': 2})))
    assert league_slots(metadata) == ('PG', 'C', 'C')
    assert league_slots(metadata, True) == ('PG', 'C', 'C', 'BE', 'BE', 'BE')
    assert can_play_slot({'position': 'SF'}, 'SG/SF')


def test_punt_limits_for_eight_categories(monkeypatch):
    categories = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%']
    monkeypatch.setattr(punt_advisor, 'CATEGORIES', categories)
    result = punt_advisor.analyze_punt_strategies({1: dict.fromkeys(categories, 1), 2: dict.fromkeys(categories, 0)}, 1, [])
    assert result['winning_categories'] == 5
    assert result['baseline']['margin_for_error'] == 3
    assert result['max_punts'] == 3
    assert all(row['available_categories'] >= 5 for row in result['strategy_options'])


def test_manual_roster_preserves_untraded_members():
    assert selected_names_after_trade(['A', 'B'], ['A'], ['C']) == ['B', 'C']


def test_accrued_ratios_are_recomputed_from_volume():
    result = combine_stats({'FGM': 9, 'FGA': 10, 'AST': 5, 'TO': 2}, {'FGM': 1, 'FGA': 10, 'AST': 3, 'TO': 2})
    assert result['FG%'] == .5
    assert result['A/TO'] == 2


def test_started_games_not_forecast_twice_and_return_date_is_used():
    now = datetime.now()
    player = {'name': 'A', 'position': 'PG', 'available': False, 'expected_return_date': now.date() + timedelta(days=1), 'future_only': True,
              'schedule': {'1': {'date': now - timedelta(hours=1)}, '2': {'date': now + timedelta(days=2)}}, 'z_scores': {'PTS': 1}}
    result = build_matchup_lineups([player], [1, 2], ('PG',))
    assert result['selected_games'] == {'A': 1}


def test_refresh_retains_successful_state_on_scoring_failure(monkeypatch):
    import core.league_metadata as module
    metadata = module.LeagueMetadata()
    old_league = SimpleNamespace(teams=['old'])
    metadata.league, metadata.teams = old_league, ['old']
    monkeypatch.setattr(module, 'League', lambda **kwargs: SimpleNamespace(teams=['new']))
    monkeypatch.setattr(metadata, '_configure_scoring', lambda: (_ for _ in ()).throw(RuntimeError('offline')))
    assert metadata.connect_to_league() is False
    assert metadata.league is old_league
    assert metadata.teams == ['old']


def test_matchup_utility_rewards_contested_category_over_already_locked(monkeypatch):
    import core.matchup_value as module
    monkeypatch.setattr(module, 'CATEGORIES', ['PTS', 'BLK'])
    opponent = {'PTS': 100, 'BLK': 10}
    assert matchup_utility({'PTS': 200, 'BLK': 11}, opponent) > matchup_utility({'PTS': 220, 'BLK': 9}, opponent)


def test_forecasts_are_frozen_and_validated_without_lookahead(tmp_path, monkeypatch):
    from web.backend.services.forecast_history import record, validate
    monkeypatch.setenv('FORECAST_DB', str(tmp_path / 'forecasts.db'))
    record(1, 2030, 2, 1, 2, 'total', {'TO': 2}, {'TO': 10}, ['TO'], ['TO'])
    record(1, 2030, 2, 1, 2, 'total', {'TO': 100}, {'TO': 1}, ['TO'], ['TO'])
    league = SimpleNamespace(league_id=1, year=2030, league=SimpleNamespace(currentMatchupPeriod=2),
                             get_all_teams_stats_for_week=lambda week: {1: {'stats': {'TO': 3}}, 2: {'stats': {'TO': 8}}})
    assert validate(league)['resolved'] == 0
    league.league.currentMatchupPeriod = 3
    result = validate(league)
    assert result['resolved'] == 1
    assert result['matchup_accuracy'] == 1
    assert result['category_mae']['TO'] == 1.5


def test_access_token_is_required_when_configured(monkeypatch):
    from web.backend.access import authorized
    monkeypatch.setenv('NBA_API_TOKEN', 'example-test-token')
    assert not authorized('')
    assert not authorized('Bearer wrong')
    assert authorized('Bearer example-test-token')


def test_initial_connection_failure_is_not_cached(monkeypatch):
    from web.backend import dependencies
    from fastapi import HTTPException
    dependencies.get_league_meta.cache_clear()
    monkeypatch.setattr(dependencies, 'LeagueMetadata', lambda: SimpleNamespace(connect_to_league=lambda: False))
    with pytest.raises(HTTPException) as error:
        dependencies.get_league_meta()
    assert error.value.status_code == 503
    assert dependencies.get_league_meta.cache_info().currsize == 0


def test_waivers_protect_injured_assets_and_rank_real_gain(monkeypatch):
    from web.backend.services import waivers
    date = datetime.now() + timedelta(days=2)
    def player(name, pts, available=True):
        return {'name': name, 'position': 'PG', 'team_id': 1, 'team_name': 'Team', 'stats': {'PTS': pts}, 'z_scores': {'PTS': pts / 10},
                'available': available, 'injured': not available, 'schedule': {'1': {'date': date}}}
    own = [player('Star', 30), player('Injured star', 29, False), player('Weak', 2), player('Backup', 3)]
    other = [player('Opponent', 60)]
    def snapshot_players(team_id):
        return [SimpleNamespace(as_projection_player=lambda p=p: p.copy()) for p in (own if team_id == 1 else other)]
    snapshot = SimpleNamespace(team_players=snapshot_players, active_slots=('UT', 'UT', 'UT'), league_metrics={'PTS': {'mean': 10, 'std': 5}})
    monkeypatch.setattr(waivers, 'build_league_snapshot', lambda *args: snapshot)
    candidate = SimpleNamespace(name='Add', playerId=10, position='PG', eligibleSlots=['PG'], schedule={'1': {'date': date}}, injured=False)
    league = SimpleNamespace(currentMatchupPeriod=1, current_week=1, matchup_ids={1: [1]}, player_info=lambda **kwargs: [candidate])
    meta = SimpleNamespace(league=league, year=2030, get_free_agents=lambda **kwargs: [candidate],
        get_player_stats=lambda *args: {'PTS': 40}, get_all_players_stats=lambda *args: own,
        get_matchup_box_score=lambda week, team: {'totals': {}, 'opponent_id': 2 if team == 1 else 1})
    result = waivers.recommend_free_agents(meta, 1, 'total')
    assert result['players']
    assert result['players'][0]['drop_player'] in {'Weak', 'Backup'}
    assert result['players'][0]['matchup_gain'] > 0


def test_background_jobs_deduplicate_without_waiting():
    from threading import Event
    from web.backend.services import jobs
    event = Event()
    try:
        job_id = jobs.submit(('unit-test',), lambda: event.wait(3))
        assert jobs.submit(('unit-test',), lambda: None) == job_id
        assert jobs.status(job_id)['status'] in {'queued', 'running'}
    finally:
        event.set()


def test_trade_rejects_players_not_owned_by_sender():
    from core.trade_roster import validate_ownership
    with pytest.raises(ValueError):
        validate_ownership({1: {'A'}, 2: {'B'}}, {1: {'give': ['B'], 'receive': ['A']}, 2: {'give': ['A'], 'receive': ['B']}})


def test_season_uses_accrued_score_and_only_remaining_days(monkeypatch):
    from web.backend.services import season
    teams = [SimpleNamespace(team_id=i, team_name=str(i), wins=0, losses=0, ties=0, standing=i) for i in (1, 2)]
    league = SimpleNamespace(settings=SimpleNamespace(reg_season_count=1), currentMatchupPeriod=1, current_week=2, matchup_ids={1: [1, 2]})
    metadata = SimpleNamespace(league=league, get_teams=lambda: teams,
        get_schedule_matchups=lambda *args: [{'matchup_period': 1, 'team1_id': 1, 'team2_id': 2}],
        get_matchup_box_score=lambda week, team: {'totals': {'PTS': 100 if team == 1 else 0}})
    monkeypatch.setattr(season, 'build_league_snapshot', lambda *args: None)
    def project(snapshot, teams, days, **kwargs):
        assert days == [2]
        assert kwargs['future_only'] is True
        return {1: {'stats': {'PTS': 3}}, 2: {'stats': {'PTS': 4}}}, {}
    monkeypatch.setattr(season, 'project_snapshot_for_matchup', project)
    result = season.project_regular_season(metadata, 'total')
    assert result['standings'][0]['team_id'] == 1
    assert result['standings'][0]['wins'] == 1
