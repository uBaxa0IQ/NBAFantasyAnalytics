"""Training utilities for variable-category V8 episode shards."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from .v8_network import UniversalPolicyValue
from .v8_state import CATEGORY_VOCAB


class UniversalEpisodes(Dataset):
    def __init__(self, directory):
        self.paths = sorted(Path(directory).glob('*.npz'))
        self.index = []
        self.scenarios = set()
        self.formats = set()
        self.sample_formats = []
        self.format_counts = {}
        for path in self.paths:
            with np.load(path, allow_pickle=False) as data:
                self.scenarios.add(str(data['scenario']))
                format_id = str(data['format_id']); count = len(data['policy'])
                self.formats.add(format_id); self.format_counts[format_id] = self.format_counts.get(format_id, 0) + count
                self.index.extend((path, row) for row in range(count)); self.sample_formats.extend([format_id] * count)
        if not self.index:
            raise ValueError(f'No universal episode shards: {directory}')
        self.cached_path = None
        self.cache = None

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        path, row = self.index[index]
        if path != self.cached_path:
            with np.load(path, allow_pickle=False) as data:
                self.cache = {key: data[key] for key in ('raw', 'category_values', 'category_ids', 'category_meta',
                    'category_mask', 'roles', 'global_state', 'legal', 'loss_mask', 'policy',
                    'value_categories', 'value_events')}
            self.cached_path = path
        result = {key: torch.from_numpy(self.cache[key][row].copy()) for key in
                  ('raw', 'category_values', 'roles', 'global_state', 'legal', 'loss_mask', 'policy',
                   'value_categories', 'value_events')}
        # Category descriptors are stored once per episode, not repeated per state.
        for key in ('category_ids', 'category_meta', 'category_mask'):
            value = self.cache[key]
            result[key] = torch.from_numpy(value.copy())
        return result


def collate_universal(rows):
    max_categories = max(len(row['category_ids']) for row in rows)
    padding_id = len(CATEGORY_VOCAB)
    result = {}
    for key in ('raw', 'roles', 'global_state', 'legal', 'loss_mask', 'policy', 'value_events'):
        result[key] = torch.stack([row[key] for row in rows])
    batch = len(rows); players = rows[0]['category_values'].shape[0]
    result['category_values'] = torch.zeros((batch, players, max_categories), dtype=torch.float32)
    result['category_ids'] = torch.full((batch, max_categories), padding_id, dtype=torch.long)
    result['category_meta'] = torch.zeros((batch, max_categories, 2), dtype=torch.float32)
    result['category_mask'] = torch.zeros((batch, max_categories), dtype=torch.bool)
    result['value_categories'] = torch.zeros((batch, max_categories), dtype=torch.float32)
    for index, row in enumerate(rows):
        count = len(row['category_ids'])
        result['category_values'][index, :, :count] = row['category_values']
        result['category_ids'][index, :count] = row['category_ids']
        result['category_meta'][index, :count] = row['category_meta']
        result['category_mask'][index, :count] = row['category_mask']
        result['value_categories'][index, :count] = row['value_categories']
    return result


def batch_loss(model, batch):
    logits, category_logits, event_logits = model(batch['raw'], batch['category_values'], batch['category_ids'],
        batch['category_meta'], batch['category_mask'], batch['roles'], batch['global_state'], batch['legal'])
    policy_scores = logits.masked_fill(~batch['loss_mask'], -1e9)
    policy_loss = -(batch['policy'] * F.log_softmax(policy_scores, dim=-1)).sum(-1).mean()
    category_raw = F.binary_cross_entropy_with_logits(category_logits, batch['value_categories'], reduction='none')
    category_loss = (category_raw * batch['category_mask']).sum() / batch['category_mask'].sum().clamp_min(1)
    rank_loss = F.smooth_l1_loss(event_logits[:, 0].sigmoid(), batch['value_events'][:, 0])
    event_loss = F.binary_cross_entropy_with_logits(event_logits[:, 1:], batch['value_events'][:, 1:])
    loss = policy_loss + category_loss + rank_loss + .25 * event_loss
    return loss, {
        'loss': float(loss.detach()), 'policy_loss': float(policy_loss.detach()),
        'top1_agreement': float((policy_scores.argmax(-1) == batch['policy'].argmax(-1)).float().mean()),
        'category_mae': float((((category_logits.sigmoid() - batch['value_categories']).abs() * batch['category_mask']).sum()
                              / batch['category_mask'].sum().clamp_min(1)).detach()),
        'rank_mae': float((event_logits[:, 0].sigmoid() - batch['value_events'][:, 0]).abs().mean().detach()),
    }


def atomic_torch(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + '.tmp')
    torch.save(payload, temporary)
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.25)


def atomic_json(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.25)


def fit(config, data_path, output, provenance, warm_start):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    train = UniversalEpisodes(Path(data_path) / 'train'); validation = UniversalEpisodes(Path(data_path) / 'validation')
    if train.scenarios & validation.scenarios:
        raise ValueError('Universal train/validation scenario leakage')
    settings = config['training']; device = ('cuda' if torch.cuda.is_available() else 'cpu') if settings['device'] == 'auto' else settings['device']
    if device == 'cuda' and not torch.cuda.is_available(): raise ValueError('CUDA requested but unavailable')
    payload = torch.load(warm_start, map_location='cpu', weights_only=True)
    spec = dict(payload['spec']); spec.pop('category_vocab', None)
    model = UniversalPolicyValue(**spec).to(device); model.load_state_dict(payload['model'])
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings['learning_rate'], weight_decay=settings['weight_decay'])
    latest = output / 'last.pt'; start = 0; best = float('inf'); stale = 0; history = []
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=True)
        if saved['provenance'] != provenance: raise ValueError('Universal training inputs changed')
        model.load_state_dict(saved['model']); optimizer.load_state_dict(saved['optimizer'])
        start, best, stale, history = saved['epoch'], saved['best'], saved['stale'], saved['history']
    if (output / 'complete.json').exists(): return
    torch.set_num_threads(2)
    validation_loader = DataLoader(validation, batch_size=settings['batch_size'], shuffle=False, collate_fn=collate_universal)
    for epoch in range(start, settings['epochs']):
        if stale >= settings['patience']: break
        generator = torch.Generator().manual_seed(config['seed'] + epoch)
        sample_weights = [1.0 / train.format_counts[format_id] for format_id in train.sample_formats]
        sampler = WeightedRandomSampler(sample_weights, num_samples=len(train), replacement=True, generator=generator)
        loader = DataLoader(train, batch_size=settings['batch_size'], sampler=sampler, collate_fn=collate_universal)
        model.train()
        for batch in loader:
            batch = {key: value.to(device) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True); loss, _ = batch_loss(model, batch)
            if not torch.isfinite(loss): raise FloatingPointError('Non-finite universal loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
        model.eval(); sums = {}; count = 0
        with torch.inference_mode():
            for batch in validation_loader:
                batch = {key: value.to(device) for key, value in batch.items()}
                _, metrics = batch_loss(model, batch); size = len(batch['policy']); count += size
                for key, value in metrics.items(): sums[key] = sums.get(key, 0.0) + value * size
        metrics = {key: value / count for key, value in sums.items()}; history.append({'epoch': epoch + 1, **metrics})
        improved = metrics['loss'] < best - settings['minimum_improvement']
        best, stale = (metrics['loss'], 0) if improved else (best, stale + 1)
        checkpoint = {'model': model.state_dict(), 'spec': model.spec, 'provenance': provenance}
        if improved: atomic_torch(output / 'best.pt', checkpoint)
        atomic_torch(latest, {**checkpoint, 'optimizer': optimizer.state_dict(), 'epoch': epoch + 1,
            'best': best, 'stale': stale, 'history': history})
        print(json.dumps({'epoch': epoch + 1, 'device': device, **metrics}), flush=True)
    atomic_json(output / 'complete.json', {'provenance': provenance, 'epochs': len(history),
        'history': history, 'best_validation_loss': best, 'train_formats': sorted(train.formats),
        'validation_formats': sorted(validation.formats)})
