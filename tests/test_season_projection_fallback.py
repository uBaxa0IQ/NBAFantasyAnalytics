from types import SimpleNamespace

import pytest

from core.config import PERIODS
from core.league_metadata import LeagueMetadata


@pytest.fixture
def metadata():
    result = LeagueMetadata()
    result.categories = ['PTS', 'AST', 'DD']
    result._projected_dd_cache[PERIODS['projected']] = {
        'rates': {1: .25}, 'historical': {}, 'sources': {},
    }
    return result


def player(season=None):
    periods = {PERIODS['projected']: {'avg': {'GP': 65, 'PTS': 20, 'AST': 5}}}
    if season is not None:
        periods[PERIODS['total']] = season
    return SimpleNamespace(playerId=1, stats=periods)


@pytest.mark.parametrize('season', [
    None, {}, {'avg': None}, {'avg': {}},
    {'avg': {'GP': 0, 'PTS': 0}},
    {'avg': {'PTS': 0}, 'total': {'GP': 0}},
])
def test_unplayed_season_uses_complete_projection_including_dd(metadata, season):
    p = player(season)
    original = repr(p.stats)
    actual = metadata.get_player_stats(p, PERIODS['total'], 'avg')
    assert actual == metadata.get_player_stats(p, PERIODS['projected'], 'avg')
    assert actual['DD'] == .25
    assert repr(p.stats) == original


def test_first_game_replaces_projection_even_with_zero_points(metadata):
    p = player({'avg': {'GP': 1, 'PTS': 0, 'AST': 2}})
    assert metadata.get_player_stats(p, PERIODS['total'], 'avg') == {
        'GP': 1, 'PTS': 0, 'AST': 2,
    }


def test_actual_totals_never_fall_back(metadata):
    assert metadata.get_player_stats(player(), PERIODS['total'], 'total') is None
    p = player({'total': {'GP': 0, 'PTS': 0}})
    assert metadata.get_player_stats(p, PERIODS['total'], 'total') == {'GP': 0, 'PTS': 0}


def test_absent_projection_stays_unavailable(metadata):
    p = SimpleNamespace(playerId=1, stats={PERIODS['total']: {'avg': {'GP': 0}}})
    assert metadata.get_player_stats(p, PERIODS['total'], 'avg') is None


def test_rolling_windows_do_not_substitute_season_forecasts(metadata):
    assert metadata.get_player_stats(player(), PERIODS['last_7'], 'avg') is None
