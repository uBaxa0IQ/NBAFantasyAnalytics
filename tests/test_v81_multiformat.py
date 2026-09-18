import json
from pathlib import Path

import numpy as np
import torch

from scripts import draft_v81_multiformat as v81
from web.backend.services.draft_ml.v8_network import UniversalPolicyValue
from web.backend.services.draft_ml.v8_train import UniversalEpisodes, batch_loss, collate_universal

ROOT = Path(__file__).resolve().parents[1]


def test_plan_has_disjoint_multiformat_holdout():
    plan = v81.plan()
    assert plan['formats'] == 12
    assert plan['holdout_formats'] == 5
    assert plan['data_drafts'] == 1320
    assert plan['searched_decisions'] == 5280
    assert plan['selection_continuations'] == 126720
    assert plan['audit_continuations_max'] == 21120
    assert plan['evaluation_drafts'] == 740


def test_punt_profiles_are_seeded_and_reference_is_no_punt():
    v81.initialize()
    case = next(row for row in v81.CTX[1]['formats'] if row['id'] == 'c11-t10-r13')
    first = v81.punt_profile(case, 'train', case['team_count'] * 7)
    assert first == v81.punt_profile(case, 'train', case['team_count'] * 7)
    assert len(first[0]) == 3
    reference = next(row for row in v81.CTX[1]['holdout_formats'] if row['id'] == 'holdout-s8-reference')
    assert v81.punt_profile(reference, 'holdout', reference['team_count'] * 3)[0] == ()


def write_shard(path, category_count, format_id, scenario=None):
    players = 6; states = 2
    raw = np.zeros((states, players, 25), dtype=np.float32)
    categories = np.zeros((states, players, category_count), dtype=np.float32)
    ids = np.arange(category_count, dtype=np.int64)
    meta = np.column_stack((np.ones(category_count), np.zeros(category_count))).astype(np.float32)
    mask = np.ones(category_count, dtype=np.bool_)
    roles = np.zeros((states, players), dtype=np.int64)
    global_state = np.zeros((states, 14), dtype=np.float32)
    legal = np.ones((states, players), dtype=np.bool_)
    policy = np.full((states, players), 1 / players, dtype=np.float32)
    value_categories = np.full((states, category_count), .5, dtype=np.float32)
    value_events = np.full((states, 3), .5, dtype=np.float32)
    np.savez_compressed(path, raw=raw, category_values=categories, category_ids=ids, category_meta=meta,
        category_mask=mask, roles=roles, global_state=global_state, legal=legal, loss_mask=legal,
        policy=policy, value_categories=value_categories, value_events=value_events,
        scenario=np.asarray(scenario or 'scenario-' + format_id), format_id=np.asarray(format_id))


def test_variable_category_collation_and_loss(tmp_path):
    write_shard(tmp_path / 'eight.npz', 8, 'eight')
    write_shard(tmp_path / 'eleven.npz', 11, 'eleven')
    dataset = UniversalEpisodes(tmp_path)
    batch = collate_universal([dataset[0], dataset[2]])
    assert batch['category_values'].shape == (2, 6, 11)
    assert batch['category_mask'][0].sum() == 8
    model = UniversalPolicyValue(width=32, heads=4, layers=1)
    loss, metrics = batch_loss(model, batch)
    assert torch.isfinite(loss)
    loss.backward()
    assert 0 <= metrics['category_mae'] <= 1


def test_tiny_episode_is_serializable_and_legal(tmp_path):
    v81.initialize()
    config, settings, snapshot, policies = v81.CTX
    settings = dict(settings, search_states_per_episode=1, search_candidates=2, search_rollouts=1,
                    audit_rollouts=1, terminal_draws=1)
    v81.CTX = config, settings, snapshot, policies
    case = {'id': 'tiny', 'categories': ['FG%', 'REB', 'AST'], 'reverse': [],
            'team_count': 2, 'slots': ['UTIL', 'UTIL']}
    path = tmp_path / 'tiny.npz'
    row = v81.generate_episode(('train', case, 0, str(path), 'test'))
    assert path.exists()
    with np.load(path, allow_pickle=False) as data:
        assert str(data['provenance']) == 'test'
        assert data['raw'].shape[0] == 2
        assert data['category_values'].shape[-1] == 3
        assert np.allclose(data['policy'].sum(1), 1.0)
    assert row['searched'] == 1


def test_one_epoch_multiformat_training_smoke(tmp_path):
    from web.backend.services.draft_ml.v8_train import fit
    data = tmp_path / 'data'; (data / 'train').mkdir(parents=True); (data / 'validation').mkdir()
    write_shard(data / 'train/eight.npz', 8, 'eight', 'train-eight')
    write_shard(data / 'train/eleven.npz', 11, 'eleven', 'train-eleven')
    write_shard(data / 'validation/eight.npz', 8, 'eight', 'validation-eight')
    write_shard(data / 'validation/eleven.npz', 11, 'eleven', 'validation-eleven')
    config = {'seed': 1, 'training': {'epochs': 1, 'batch_size': 2, 'learning_rate': 1e-5,
        'weight_decay': .01, 'patience': 1, 'minimum_improvement': 1e-4, 'device': 'cpu'}}
    output = tmp_path / 'training'
    fit(config, data, output, 'smoke', ROOT / 'artifacts/draft_ml/standard8-v80-universal/checkpoint/best.pt')
    assert (output / 'best.pt').exists()
    complete = json.loads((output / 'complete.json').read_text())
    assert complete['epochs'] == 1
    assert complete['train_formats'] == ['eight', 'eleven']
