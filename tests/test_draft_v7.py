from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
torch = pytest.importorskip('torch')

from web.backend.services.draft_ml.v7_state import State, CATEGORIES, STATS, assigned_count, unique_teacher, validate_snapshot
from web.backend.services.draft_ml.v7_network import PolicyValue, NeuralPolicy, atomic_torch
from web.backend.services.draft_ml.v7_data import Arena, initialize_worker, generate_episode, scenario_seed
from web.backend.services.draft_ml.v7_train import fit, Episodes


def players(n=8):
    return [dict(player_id=i, name=f'P{i}', position='PG', eligible_slots=['PG', 'SG'],
                 z_scores={c: (i + j) % 4 / 2 for j, c in enumerate(CATEGORIES)},
                 stats={**dict.fromkeys(STATS, 1.0), 'GP': 70., 'PTS': 10. + i, 'FGA': 10., 'FTA': 4., '3PA': 5.},
                 stats_source='previous_season') for i in range(n)]


def small_config():
    return dict(seed=77, team_count=2, rounds=2, gp_stddev=.1, stat_stddev=.1,
                model=dict(width=16, heads=2, layers=1),
                training=dict(device='cpu', epochs=1, batch_size=2, learning_rate=.001, patience=2),
                search=dict(candidates=2, rollouts=2, states_per_episode=1, temperature=.25))


def teacher():
    return [{'id': 'first', 'weights': {'general_z': 1., 'z::PTS': 1.}, 'ensemble_weight': .3},
            {'id': 'duplicate', 'weights': {'z::PTS': 1., 'general_z': 1.}, 'ensemble_weight': .7}]


def test_teacher_duplicate_merge_preserves_order_and_scores():
    state = State(players(), ['PG', 'BE'], 2, 2)
    merged = unique_teacher(teacher())
    assert len(merged) == 1
    assert merged[0]['ensemble_weight'] == pytest.approx(1.)
    before = state.teacher_scores(teacher())
    after = state.teacher_scores(merged)
    assert [a for a, _ in before] == [a for a, _ in after]
    assert np.allclose([s for _, s in before], [s for _, s in after])


def test_exact_repeated_roster_slots_and_flex_matching():
    pg, sg = players(2)
    pg['eligible_slots'] = ['PG']; sg['eligible_slots'] = ['SG']; sg['position'] = 'SG'
    assert assigned_count([pg, sg], ['G', 'PG']) == 2
    assert assigned_count([pg, pg, sg], ['PG', 'SG', 'BE']) == 3
    assert assigned_count([pg, pg, pg], ['PG', 'SG', 'BE']) == 2
    state = State([pg, sg, {**pg, 'player_id': 3}], ['PG', 'SG'], 2, 2)
    state.rosters[1] = [0]
    state.remaining = [1, 2]
    assert state.legal() == [1]
    with pytest.raises(ValueError, match='Illegal'):
        state.apply(2)


def test_targets_use_half_credit_for_ties_and_shooting_volume():
    state = State([deepcopy(players(1)[0]) for _ in range(4)], ['UT', 'BE'], 2, 2)
    for i, p in enumerate(state.players):
        p['player_id'] = i
    for i in range(4):
        state.apply(i)
    target = state.targets(1, 'fixed', 0, 0)
    assert np.allclose(target[:8], .5)
    assert target[8] == 0  # shared rank 1, not seat-based tie breaking


def test_encoding_excludes_market_fields_and_network_is_permutation_equivariant():
    torch.set_num_threads(1)
    state = State(players(), ['PG', 'BE'], 2, 2)
    a = state.encode()
    for p in state.players:
        p.update(espn_adp=999, espn_roto_rank=-100, name='changed')
    b = state.encode()
    for x, y in zip(a, b):
        assert np.array_equal(x, y)
    model = PolicyValue(width=16, heads=2, layers=1, team_count=2).eval()
    inputs = [torch.as_tensor(x)[None] for x in a]
    order = torch.tensor([3, 1, 5, 7, 6, 4, 2, 0])
    with torch.no_grad():
        p, v = model(*inputs)
        q, w = model(inputs[0][:, order], inputs[1][:, order], inputs[2], inputs[3][:, order])
    assert torch.allclose(p[:, order], q, atol=1e-5)
    assert torch.allclose(v, w, atol=1e-5)


def test_counterfactual_search_preserves_state_and_is_reproducible():
    state = State(players(), ['PG', 'BE'], 2, 2)
    arena = Arena(small_config(), teacher())
    before = (list(state.remaining), deepcopy(state.rosters), state.pick)
    first = arena.search(state, 1, 'common')
    second = arena.search(state, 1, 'common')
    assert (state.remaining, state.rosters, state.pick) == before
    for a, b in zip(first, second):
        assert np.allclose(a, b)


def test_episode_split_training_checkpoint_resume_and_neural_search(tmp_path):
    config = small_config()
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(dict(players=players(), categories=CATEGORIES, roster_slots=['PG', 'BE'])))
    teacher_path = tmp_path / 'teacher.json'; teacher_path.write_text(json.dumps(teacher()))
    initialize_worker(config, snapshot, teacher_path, None)
    for split in ('train', 'validation'):
        generate_episode((split, 0, 0, str(tmp_path / 'data' / split / '000000.npz'), 'test'))
    a, b = Episodes(tmp_path / 'data/train'), Episodes(tmp_path / 'data/validation')
    assert not a.scenarios & b.scenarios
    fit(config, tmp_path / 'data', tmp_path / 'training', 'test')
    checkpoint = tmp_path / 'training/best.pt'
    original = checkpoint.read_bytes()
    fit(config, tmp_path / 'data', tmp_path / 'training', 'test')
    assert checkpoint.read_bytes() == original
    with pytest.raises(ValueError, match='inputs changed'):
        fit(config, tmp_path / 'data', tmp_path / 'training', 'changed')
    model = NeuralPolicy(checkpoint)
    state = State(players(), ['PG', 'BE'], 2, 2)
    logits, values = model.predict(state)
    assert len(logits) == 8 and len(values) == 11
    initialize_worker(config, snapshot, teacher_path, checkpoint)
    generate_episode(('train', 1, 0, str(tmp_path / 'improvement.npz'), 'test'))
    with np.load(tmp_path / 'improvement.npz') as data:
        assert np.allclose(data['policy'].sum(1), 1.)
        assert np.all(data['policy'][~data['loss_mask']] == 0)


def test_runner_defaults_to_dry_plan_and_snapshot_audit():
    from scripts.draft_ml_v7_run import plan, CONFIG
    config = json.loads(CONFIG.read_text())
    result = plan(config)
    assert result['status'] == 'prepared_not_started'
    assert result['audit']['unique_teacher_members'] == 6
    assert result['initial_states'] == 14560
    payload = dict(players=players(26), categories=CATEGORIES, roster_slots=['UT'] * 13)
    payload['players'][0]['stats']['FGM'] = 100
    with pytest.raises(ValueError, match='shooting components'):
        validate_snapshot(payload, 2, 13)


def test_parallel_generation_and_four_arm_evaluation_resume(tmp_path):
    from web.backend.services.draft_ml.v7_data import generate
    from web.backend.services.draft_ml.v7_evaluate import evaluate
    config = {**small_config(), 'workers': 2, 'episodes': {'train': 1, 'validation': 1}, 'evaluation_runs': {'validation': 2}}
    snapshot = tmp_path / 'snapshot.json'
    snapshot.write_text(json.dumps(dict(players=players(), categories=CATEGORIES, roster_slots=['PG', 'BE'])))
    teacher_path = tmp_path / 'teacher.json'; teacher_path.write_text(json.dumps(teacher()))
    generate(config, snapshot, teacher_path, tmp_path / 'data', 0, 'test')
    episode = tmp_path / 'data/train/000000.npz'
    timestamp = episode.stat().st_mtime_ns
    generate(config, snapshot, teacher_path, tmp_path / 'data', 0, 'test')
    assert episode.stat().st_mtime_ns == timestamp
    model = PolicyValue(**config['model'], team_count=2)
    checkpoint = tmp_path / 'model.pt'
    atomic_torch(checkpoint, {'model': model.state_dict(), 'spec': model.spec})
    evaluate(config, snapshot, teacher_path, checkpoint, tmp_path / 'evaluation', 'validation', 'test')
    saved = (tmp_path / 'evaluation/summary.json').read_bytes()
    evaluate(config, snapshot, teacher_path, checkpoint, tmp_path / 'evaluation', 'validation', 'test')
    assert (tmp_path / 'evaluation/summary.json').read_bytes() == saved
    result = json.loads(saved)
    assert len(result['paired_outcomes']) == 2
    assert set(result['paired_outcomes'][0]['results']) == {'teacher', 'student', 'teacher_search', 'student_search', 'teacher_value_search', 'student_value_search'}
