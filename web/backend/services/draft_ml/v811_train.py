"""Trust-region residual training over the frozen V8.0 policy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from .v8_network import UniversalResidualPolicyValue
from .v8_train import collate_universal


def _search_rounds(rounds, count):
    return sorted({min(rounds - 1, max(0, round((index + 1) * rounds / (count + 1)) - 1))
                   for index in range(count)})


class ResidualEpisodes(Dataset):
    """V8.1 shards with masks for independently audited search improvements."""
    tensor_keys = ('raw', 'category_values', 'roles', 'global_state', 'legal', 'loss_mask', 'policy',
                   'value_categories', 'value_events')
    descriptor_keys = ('category_ids', 'category_meta', 'category_mask')

    def __init__(self, directory, search_states_per_episode):
        self.index = []
        self.sample_formats = []
        self.format_counts = {}
        self.formats = set()
        self.scenarios = set()
        for path in sorted(Path(directory).glob('*.npz')):
            with np.load(path, allow_pickle=False) as data:
                states = len(data['policy']); audits = json.loads(str(data['audits']))
                searched = _search_rounds(states, search_states_per_episode)
                if len(searched) != len(audits):
                    raise ValueError(f'Audit/state mismatch in {path}')
                accepted = np.zeros(states, dtype=np.float32); gains = np.zeros(states, dtype=np.float32)
                for row, audit in zip(searched, audits):
                    if audit['accepted']:
                        accepted[row] = 1.0; gains[row] = max(0.0, float(audit['gain']))
                format_id = str(data['format_id']); scenario = str(data['scenario'])
                self.formats.add(format_id); self.scenarios.add(scenario)
                self.format_counts[format_id] = self.format_counts.get(format_id, 0) + states
                for row in range(states):
                    self.index.append((path, row, accepted[row], gains[row]))
                    self.sample_formats.append(format_id)
        if not self.index:
            raise ValueError(f'No residual training shards: {directory}')
        self.cached_path = None
        self.cache = None

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        path, row, accepted, gain = self.index[index]
        if path != self.cached_path:
            with np.load(path, allow_pickle=False) as data:
                self.cache = {key: data[key] for key in (*self.tensor_keys, *self.descriptor_keys)}
            self.cached_path = path
        result = {key: torch.from_numpy(self.cache[key][row].copy()) for key in self.tensor_keys}
        result.update({key: torch.from_numpy(self.cache[key].copy()) for key in self.descriptor_keys})
        result['improvement_mask'] = torch.tensor(accepted, dtype=torch.float32)
        result['improvement_gain'] = torch.tensor(gain, dtype=torch.float32)
        return result


def collate_residual(rows):
    result = collate_universal(rows)
    result['improvement_mask'] = torch.stack([row['improvement_mask'] for row in rows])
    result['improvement_gain'] = torch.stack([row['improvement_gain'] for row in rows])
    return result


def residual_loss(model, batch, settings):
    with torch.no_grad():
        teacher_logits, _, _ = model.base(batch['raw'], batch['category_values'], batch['category_ids'],
            batch['category_meta'], batch['category_mask'], batch['roles'], batch['global_state'], batch['legal'])
    logits, category_logits, event_logits = model(batch['raw'], batch['category_values'], batch['category_ids'],
        batch['category_meta'], batch['category_mask'], batch['roles'], batch['global_state'], batch['legal'])
    temperature = float(settings['distillation_temperature'])
    teacher_probability = F.softmax(teacher_logits / temperature, dim=-1)
    student_log_probability = F.log_softmax(logits / temperature, dim=-1)
    teacher_log_probability = F.log_softmax(teacher_logits / temperature, dim=-1)
    distillation = (teacher_probability * (teacher_log_probability - student_log_probability)).sum(-1).mean() * temperature ** 2
    target_ce = -(batch['policy'] * F.log_softmax(logits, dim=-1)).sum(-1)
    improvement_weights = batch['improvement_mask'] * (1.0 + batch['improvement_gain'].clamp(0, 1))
    improvement = (target_ce * improvement_weights).sum() / improvement_weights.sum().clamp_min(1)
    delta = (logits - teacher_logits).masked_fill(~batch['legal'], 0.0)
    legal_count = batch['legal'].sum(-1, keepdim=True).clamp_min(1)
    centered = (delta - delta.sum(-1, keepdim=True) / legal_count).masked_fill(~batch['legal'], 0.0)
    trust = centered.square().sum() / batch['legal'].sum().clamp_min(1)
    category_raw = F.binary_cross_entropy_with_logits(category_logits, batch['value_categories'], reduction='none')
    category = (category_raw * batch['category_mask']).sum() / batch['category_mask'].sum().clamp_min(1)
    rank = F.smooth_l1_loss(event_logits[:, 0].sigmoid(), batch['value_events'][:, 0])
    events = F.binary_cross_entropy_with_logits(event_logits[:, 1:], batch['value_events'][:, 1:])
    value = category + rank + .25 * events
    loss = (settings['distillation_weight'] * distillation + settings['improvement_weight'] * improvement
            + settings['trust_weight'] * trust + settings['value_weight'] * value)
    selection = improvement + .25 * distillation + .10 * value
    return loss, {'loss': float(loss.detach()), 'selection_loss': float(selection.detach()),
        'distillation_kl': float(distillation.detach()), 'improvement_ce': float(improvement.detach()),
        'trust_mse': float(trust.detach()), 'value_loss': float(value.detach()),
        'accepted_states': float(batch['improvement_mask'].sum().detach())}


def _atomic_torch(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + '.tmp')
    torch.save(payload, temporary)
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.25)


def _atomic_json(path, payload):
    path = Path(path); temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.25)


def fit_residual(config, data_path, output, provenance, warm_start, seed):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    settings = config['training']; device = ('cuda' if torch.cuda.is_available() else 'cpu') if settings['device'] == 'auto' else settings['device']
    train = ResidualEpisodes(Path(data_path) / 'train', config['search_states_per_episode'])
    validation = ResidualEpisodes(Path(data_path) / 'validation', config['search_states_per_episode'])
    if train.scenarios & validation.scenarios:
        raise ValueError('Residual train/validation leakage')
    source = torch.load(warm_start, map_location='cpu', weights_only=True)
    torch.manual_seed(seed)
    np.random.seed(seed % (2 ** 32))
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    model = UniversalResidualPolicyValue(source['spec'], settings['adapter_width']).to(device)
    model.base.load_state_dict(source['model']); model.freeze_base()
    optimizer = torch.optim.AdamW(list(model.adapter_parameters()), lr=settings['learning_rate'],
                                  weight_decay=settings['weight_decay'])
    latest = output / 'last.pt'; start = 0; best = float('inf'); stale = 0; history = []
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=True)
        if saved['provenance'] != provenance or saved['seed'] != seed:
            raise ValueError('Residual resume provenance mismatch')
        model.load_state_dict(saved['model']); optimizer.load_state_dict(saved['optimizer'])
        start, best, stale, history = saved['epoch'], saved['best'], saved['stale'], saved['history']
    if (output / 'complete.json').exists(): return
    torch.set_num_threads(2)
    validation_loader = DataLoader(validation, batch_size=settings['batch_size'], shuffle=False, collate_fn=collate_residual)
    for epoch in range(start, settings['epochs']):
        if stale >= settings['patience']: break
        generator = torch.Generator().manual_seed(seed + epoch)
        weights = [1.0 / train.format_counts[format_id] for format_id in train.sample_formats]
        sampler = WeightedRandomSampler(weights, len(train), replacement=True, generator=generator)
        loader = DataLoader(train, batch_size=settings['batch_size'], sampler=sampler, collate_fn=collate_residual)
        model.train()
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True); loss, _ = residual_loss(model, batch, settings)
            if not torch.isfinite(loss): raise FloatingPointError('Non-finite residual loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(list(model.adapter_parameters()), 1.0); optimizer.step()
        model.eval(); sums = {}; count = 0
        with torch.inference_mode():
            for batch in validation_loader:
                batch = {key: value.to(device) for key, value in batch.items()}
                _, metrics = residual_loss(model, batch, settings); size = len(batch['policy']); count += size
                for key, value in metrics.items(): sums[key] = sums.get(key, 0.0) + value * size
        metrics = {key: value / count for key, value in sums.items()}; history.append({'epoch': epoch + 1, **metrics})
        improved = metrics['selection_loss'] < best - settings['minimum_improvement']
        best, stale = (metrics['selection_loss'], 0) if improved else (best, stale + 1)
        checkpoint = {'model': model.state_dict(), 'spec': model.spec, 'adapter_scale': 1.0,
            'provenance': provenance, 'seed': seed, 'source_checkpoint_sha256': hashlib.sha256(Path(warm_start).read_bytes()).hexdigest()}
        if improved: _atomic_torch(output / 'best.pt', checkpoint)
        _atomic_torch(latest, {**checkpoint, 'optimizer': optimizer.state_dict(), 'epoch': epoch + 1,
            'best': best, 'stale': stale, 'history': history})
        print(json.dumps({'seed': seed, 'epoch': epoch + 1, 'device': device, **metrics}), flush=True)
    _atomic_json(output / 'complete.json', {'provenance': provenance, 'seed': seed, 'epochs': len(history),
        'best_selection_loss': best, 'history': history, 'train_formats': sorted(train.formats),
        'validation_formats': sorted(validation.formats)})


def scaled_checkpoint(source, destination, scale, provenance):
    payload = torch.load(source, map_location='cpu', weights_only=True)
    if payload['provenance'] != provenance:
        raise ValueError('Cannot scale checkpoint from another experiment')
    payload['adapter_scale'] = float(scale)
    _atomic_torch(destination, payload)
    return Path(destination)
