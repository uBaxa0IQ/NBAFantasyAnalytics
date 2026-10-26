from core.trade_roster import selected_roster_after_trade
from types import SimpleNamespace

import pytest

from models import MultiTeamTradeRequest, TeamTrade, TradeAnalysisRequest
from routers import trades
from services import trades as trade_services


def player(name, z):
    return {'name': name, 'z_scores': {'PTS': z}}


def test_one_for_one_keeps_other_manual_selections():
    after = [player('B', 2), player('C', 1), player('Incoming', 0), player('Bench', 10)]
    assert selected_roster_after_trade(
        ['Outgoing', 'B', 'C'], ['Outgoing'], ['Incoming'], after, 3,
    ) == ['B', 'C', 'Incoming']


def test_one_for_two_drops_weakest_of_the_fourteen_selected():
    selected = [f'Kept {number}' for number in range(12)] + ['Outgoing']
    after = [player(name, 2) for name in selected[:-1]] + [
        player('Incoming weak', -3), player('Incoming strong', 5), player('Bench', 20),
    ]
    result = selected_roster_after_trade(
        selected, ['Outgoing'], ['Incoming weak', 'Incoming strong'], after, 13,
    )
    assert len(result) == 13
    assert 'Incoming strong' in result
    assert 'Incoming weak' not in result
    assert 'Bench' not in result


def test_two_for_one_fills_open_selection_from_bench():
    after = [player('Kept', 2), player('Incoming', 1), player('Best bench', 3), player('Other bench', -1)]
    assert selected_roster_after_trade(
        ['Outgoing A', 'Outgoing B', 'Kept'],
        ['Outgoing A', 'Outgoing B'], ['Incoming'], after, 3,
    ) == ['Kept', 'Incoming', 'Best bench']


def test_trade_of_unselected_player_does_not_replace_manual_selection():
    after = [player('Selected A', 1), player('Selected B', 2), player('Incoming', 10)]
    assert selected_roster_after_trade(
        ['Selected A', 'Selected B'], ['Bench'], ['Incoming'], after, 2,
    ) == ['Selected A', 'Selected B']


@pytest.mark.parametrize('multi_team', [False, True])
def test_trade_rankings_use_the_same_manual_roster_as_raw_totals(monkeypatch, multi_team):
    roster = {
        1: [player('Outgoing', 5), player('Selected', 2), player('Bench', 10)],
        2: [player('Incoming', 1), player('Opponent', 0)],
    }
    players = [
        {**entry, 'team_id': team_id, 'team_name': str(team_id)}
        for team_id, entries in roster.items() for entry in entries
    ]

    class League:
        def get_teams(self):
            return [SimpleNamespace(team_id=team_id, team_name=str(team_id)) for team_id in roster]

        def get_team_roster(self, team_id):
            return [SimpleNamespace(name=entry['name']) for entry in roster[team_id]]

        def get_all_players_stats(self, period, stats_type, exclude_ir=False):
            return [
                {'name': entry['name'], 'stats': {'PTS': entry['z_scores']['PTS']}}
                for entry in players
            ]

    monkeypatch.setattr(trades, 'log_trade', lambda **kwargs: None)
    monkeypatch.setattr(trades, 'calculate_z_scores', lambda *args, **kwargs: {'players': players})
    monkeypatch.setattr('core.z_score.calculate_z_scores', lambda *args, **kwargs: {'players': players})
    calendar_selections = []
    monkeypatch.setattr(
        trades, 'analyze_calendar_trade',
        lambda *args: calendar_selections.append((args[-2], args[-1])) or {},
    )
    common = dict(period='2027_total', simulation_mode='top_n', top_n_players=2,
                  custom_team_players={1: ['Outgoing', 'Selected']}, calculation_engine='calendar')

    if multi_team:
        request = MultiTeamTradeRequest(
            trades=[TeamTrade(team_id=1, give=['Outgoing'], receive=['Incoming']),
                    TeamTrade(team_id=2, give=['Incoming'], receive=['Outgoing'])],
            **common,
        )
        result = trades.analyze_multi_team_trade(request, None, League())
        raw = next(team for team in result['teams'] if team['team_id'] == 1)['raw_categories']['PTS']
        rank = result['category_rankings'][1]['PTS']
    else:
        request = TradeAnalysisRequest(
            my_team_id=1, their_team_id=2, i_give=['Outgoing'], i_receive=['Incoming'],
            **common,
        )
        result = trades.analyze_trade(request, None, League())
        raw = result['my_team']['raw_categories']['PTS']
        rank = result['category_rankings']['my_team']['PTS']

    assert raw['after'] == 3
    assert rank['after'] == 2
    assert calendar_selections == [({1: {'Outgoing', 'Selected'}, 2: {'Incoming', 'Opponent'}},
                                    {1: {'Selected', 'Incoming'}, 2: {'Outgoing', 'Opponent'}})]


def test_calendar_trade_uses_selected_players_for_both_scenarios(monkeypatch):
    original = [player('Outgoing', 3), player('Selected', 2), player('Bench', 10)]
    received = player('Incoming', 1)
    class Snapshot:
        players = [SimpleNamespace(name=entry['name'], as_projection_player=lambda entry=entry: entry)
                   for entry in original + [received]]
        active_slots = ('UT',)

        def team_players(self, team_id):
            return self.players[:3]

    projected = []
    monkeypatch.setattr(trade_services, 'build_league_snapshot', lambda *args: Snapshot())
    monkeypatch.setattr(trade_services, 'get_remaining_scoring_periods', lambda *args: [1])
    monkeypatch.setattr(trade_services, '_project',
                        lambda players, *args: projected.append({p['name'] for p in players}) or (0, {}, 0))
    metadata = SimpleNamespace(league=SimpleNamespace(currentMatchupPeriod=1))
    trade_services.analyze_calendar_trade(
        metadata, '2027_total', {1: {'give': ['Outgoing'], 'receive': ['Incoming']}},
        selected_before={1: {'Outgoing', 'Selected'}},
        selected_after={1: {'Selected', 'Incoming'}},
    )
    assert projected == [{'Outgoing', 'Selected'}, {'Selected', 'Incoming'}]


def test_probabilistic_trade_uses_selected_players_for_both_scenarios(monkeypatch):
    rosters = {
        1: [player('Outgoing', 3), player('Selected', 2), player('Bench', 10)],
        2: [player('Incoming', 1), player('Opponent', 0)],
    }
    monkeypatch.setattr(trade_services, 'build_engine_inputs', lambda *args: {'players_by_team': rosters})
    monkeypatch.setattr(trade_services, 'find_opponent', lambda *args: 2)
    overrides = []

    def simulate(*args, roster_overrides=None, **kwargs):
        overrides.append({team: {p['name'] for p in roster} for team, roster in roster_overrides.items()})
        return {'seed': 1, 'p_win': 0.5}

    monkeypatch.setattr(trade_services, 'simulate_pair', simulate)
    monkeypatch.setattr(trade_services, 'odds_delta', lambda *args: {})
    season_overrides = []

    def season(*args, roster_overrides=None, **kwargs):
        season_overrides.append({team: {p['name'] for p in roster} for team, roster in roster_overrides.items()})
        return {'standings': []}

    monkeypatch.setattr(trade_services, 'project_regular_season_probabilistic', season)
    metadata = SimpleNamespace(league=SimpleNamespace(currentMatchupPeriod=1))
    trade_services.analyze_probabilistic_trade(
        metadata, '2027_total', {1: {'give': ['Outgoing'], 'receive': ['Incoming']}},
        selected_before={1: {'Outgoing', 'Selected'}},
        selected_after={1: {'Selected', 'Incoming'}},
    )
    assert overrides == [{1: {'Outgoing', 'Selected'}}, {1: {'Selected', 'Incoming'}}]
    assert season_overrides == overrides
