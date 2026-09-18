import json
from pathlib import Path

import numpy as np
import torch

from scripts import draft_v811_residual as v811
from web.backend.services.draft_ml.v8_network import UniversalPolicy, UniversalPolicyValue, UniversalResidualPolicyValue
from web.backend.services.draft_ml.v811_train import (ResidualEpisodes, collate_residual, fit_residual,
    residual_loss, scaled_checkpoint)

ROOT = Path(__file__).resolve().parents[1]
WARM = ROOT / 'artifacts/draft_ml/standard8-v80-universal/checkpoint/best.pt'


def encoded(batch=2, players=7, categories=8):
    raw = torch.randn(batch, players, 25)
    values = torch.randn(batch, players, categories)
    ids = torch.arange(categories).repeat(batch, 1)
    meta = torch.zeros(batch, categories, 2); meta[:, :, 0] = 1
    mask = torch.ones(batch, categories, dtype=torch.bool)
    roles = torch.zeros(batch, players, dtype=torch.long)
    global_state = torch.randn(batch, 14)
    legal = torch.ones(batch, players, dtype=torch.bool)
    return raw, values, ids, meta, mask, roles, global_state, legal


def test_plan_reuses_v81_data_and_does_not_start_generation():
    plan = v811.plan()
    assert plan['source_shards_reused'] == 1320
    assert plan['new_generation_drafts'] == 0
    assert plan['seeds'] == 3
    assert plan['scales_per_seed'] == 5
    assert plan['validation_candidate_drafts'] == 7920
    assert plan['sealed_holdout_drafts'] == 212


def test_zero_residual_is_exact_v80_parity():
    source = torch.load(WARM, map_location='cpu', weights_only=True)
    base = UniversalPolicyValue(**{k: v for k, v in source['spec'].items() if k != 'category_vocab'})
    base.load_state_dict(source['model']); base.eval()
    residual = UniversalResidualPolicyValue(source['spec'], adapter_width=16, adapter_scale=0.0)
    residual.base.load_state_dict(source['model']); residual.eval()
    args = encoded()
    with torch.inference_mode():
        expected = base(*args); actual = residual(*args)
    for left, right in zip(expected, actual):
        assert torch.equal(left, right)


def write_residual_shard(path, scenario='scenario'):
    states, players, categories = 8, 7, 8
    legal = np.ones((states, players), dtype=np.bool_)
    policy = np.full((states, players), 1 / players, dtype=np.float32)
    audits = [{'accepted': True, 'gain': .2}, {'accepted': False, 'gain': -.1},
              {'accepted': True, 'gain': .1}, {'accepted': False, 'gain': 0.0}]
    np.savez_compressed(path, raw=np.zeros((states, players, 25), np.float32),
        category_values=np.zeros((states, players, categories), np.float32),
        category_ids=np.arange(categories, dtype=np.int64),
        category_meta=np.column_stack((np.ones(categories), np.zeros(categories))).astype(np.float32),
        category_mask=np.ones(categories, np.bool_), roles=np.zeros((states, players), np.int64),
        global_state=np.zeros((states, 14), np.float32), legal=legal, loss_mask=legal, policy=policy,
        value_categories=np.full((states, categories), .5, np.float32),
        value_events=np.full((states, 3), .5, np.float32), scenario=np.asarray(scenario),
        format_id=np.asarray('format'), audits=np.asarray(json.dumps(audits)))


def test_only_audited_improvements_move_frozen_adapter(tmp_path):
    write_residual_shard(tmp_path / 'episode.npz')
    dataset = ResidualEpisodes(tmp_path, 4)
    batch = collate_residual([dataset[i] for i in range(8)])
    assert batch['improvement_mask'].sum() == 2
    source = torch.load(WARM, map_location='cpu', weights_only=True)
    model = UniversalResidualPolicyValue(source['spec'], adapter_width=16)
    model.base.load_state_dict(source['model']); model.freeze_base()
    settings = {'distillation_temperature': 1.5, 'distillation_weight': 1.0, 'improvement_weight': 1.0,
                'trust_weight': .05, 'value_weight': .15}
    loss, metrics = residual_loss(model, batch, settings); loss.backward()
    assert torch.isfinite(loss) and metrics['accepted_states'] == 2
    assert all(parameter.grad is None for parameter in model.base.parameters())
    assert any(parameter.grad is not None for parameter in model.adapter_parameters())


def test_scaled_checkpoint_loads_through_universal_policy(tmp_path):
    source = torch.load(WARM, map_location='cpu', weights_only=True)
    model = UniversalResidualPolicyValue(source['spec'], adapter_width=8)
    model.base.load_state_dict(source['model'])
    raw = tmp_path / 'raw.pt'; scaled = tmp_path / 'scaled.pt'
    torch.save({'model': model.state_dict(), 'spec': model.spec, 'adapter_scale': 1.0,
                'provenance': 'test', 'seed': 1}, raw)
    scaled_checkpoint(raw, scaled, .25, 'test')
    loaded = UniversalPolicy(scaled)
    assert loaded.model.adapter_scale == .25


def test_zero_scale_candidate_reproduces_saved_v80_scenario(tmp_path):
    source = torch.load(WARM, map_location='cpu', weights_only=True)
    model = UniversalResidualPolicyValue(source['spec'], adapter_width=8, adapter_scale=0.0)
    model.base.load_state_dict(source['model'])
    checkpoint = tmp_path / 'zero.pt'
    torch.save({'model': model.state_dict(), 'spec': model.spec, 'adapter_scale': 0.0,
                'provenance': 'test', 'seed': 1}, checkpoint)
    from scripts import draft_v81_multiformat as v81
    v81.initialize(str(checkpoint))
    case = next(row for row in v81.CTX[1]['formats'] if row['id'] == 's8-t10-r13')
    candidate = v811.candidate_episode(('validation_eval', case, 0))
    baseline = json.loads((ROOT / 'artifacts/draft_ml/v81-multiformat/validation_eval/s8-t10-r13-00000.json').read_text())
    assert candidate['scenario'] == baseline['scenario']
    assert np.array_equal(candidate['result'], baseline['results']['v80'])


def test_one_epoch_residual_fit_smoke(tmp_path):
    data = tmp_path / 'data'; (data / 'train').mkdir(parents=True); (data / 'validation').mkdir()
    write_residual_shard(data / 'train/train.npz', 'train')
    write_residual_shard(data / 'validation/validation.npz', 'validation')
    config = {'search_states_per_episode': 4, 'training': {'epochs': 1, 'batch_size': 4,
        'learning_rate': 1e-4, 'weight_decay': .01, 'patience': 1, 'minimum_improvement': 1e-4,
        'adapter_width': 8, 'distillation_temperature': 1.5, 'distillation_weight': 1.0,
        'improvement_weight': 1.0, 'trust_weight': .05, 'value_weight': .15, 'device': 'cpu'}}
    output = tmp_path / 'training'
    fit_residual(config, data, output, 'smoke', WARM, 123)
    assert (output / 'best.pt').exists()
    complete = json.loads((output / 'complete.json').read_text())
    assert complete['epochs'] == 1 and complete['seed'] == 123


def test_validation_gate_requires_v80_improvement():
    gates = {'standard8_delta_min': -.01, 'standard8_interval_low_min': -.04,
             'universal_v80_delta_min': .005, 'universal_v80_interval_low_min': -.005,
             'universal_heuristic_delta_min': 0.0}
    def summary(universal):
        metric = lambda delta, low=None: {'delta': delta, 'interval': [delta if low is None else low, delta + .01]}
        return {'primary': {'standard8_v811_vs_v80': {'normalized_categories': metric(-.005, -.02)},
            'universal_v811_vs_v80': {'normalized_categories': metric(universal, -.002)},
            'universal_v811_vs_heuristic': {'normalized_categories': metric(.1, .08)}}}
    assert v811.qualifying_score(summary(.01), gates)[0]
    assert not v811.qualifying_score(summary(0.0), gates)[0]
