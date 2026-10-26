from types import SimpleNamespace

from web.backend.services.projections import project_snapshot_for_matchup, select_projection_roster


def test_projection_roster_modes_keep_bench_candidates_and_apply_selection():
    players = [
        {'name': 'Starter', 'lineup_slot': 'PG', 'z_scores': {'AST': 2}},
        {'name': 'Bench', 'lineup_slot': 'BE', 'z_scores': {'AST': 3}},
        {'name': 'Injured', 'lineup_slot': 'IR', 'z_scores': {'AST': 4}},
    ]
    assert [p['name'] for p in select_projection_roster(players)] == ['Starter', 'Bench', 'Injured']
    assert [p['name'] for p in select_projection_roster(players, 'exclude_ir')] == ['Starter', 'Bench']
    assert [p['name'] for p in select_projection_roster(players, 'top_n', 1)] == ['Injured']
    assert [p['name'] for p in select_projection_roster(players, 'top_n', 1, ['Bench'])] == ['Bench']


def test_calendar_projection_uses_selected_bench_player_on_game_day(monkeypatch):
    from web.backend.services import projections

    def player(name, z):
        return SimpleNamespace(as_projection_player=lambda: {
            'name': name, 'position': 'PG', 'eligible_slots': ['PG'],
            'lineup_slot': 'BE' if name == 'Bench' else 'PG',
            'available': True, 'schedule': {'1': {}},
            'z_scores': {'AST': z}, 'stats': {'AST': z},
        })

    snapshot = SimpleNamespace(
        team_players=lambda team_id: (player('Starter', 1), player('Bench', 3)),
        active_slots=('PG',),
    )
    team = SimpleNamespace(team_id=1, team_name='Team')
    _, all_lineups = project_snapshot_for_matchup(snapshot, [team], [1])
    _, selected_lineups = project_snapshot_for_matchup(
        snapshot, [team], [1], simulation_mode='top_n', top_n_players=1,
        custom_team_id=1, custom_team_players=('Starter',),
    )
    assert all_lineups[1]['selected_games']['Bench'] == 1
    assert selected_lineups[1]['selected_games'] == {'Starter': 1}
