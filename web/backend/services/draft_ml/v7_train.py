"""Epoch-resumable supervised policy/value training with whole-draft splits."""
from __future__ import annotations

import json
from pathlib import Path
import random

import numpy as np
import torch
from torch.nn import functional as F
from torch.utils.data import Dataset, DataLoader, ConcatDataset, WeightedRandomSampler

from .v7_data import atomic_json
from .v7_network import PolicyValue, NeuralPolicy, atomic_torch, resolve_device


class Episodes(Dataset):
    def __init__(self, directory):
        self.paths = sorted(Path(directory).glob('*.npz'))
        self.index = []
        self.scenarios = set()
        for path in self.paths:
            with np.load(path, allow_pickle=False) as data:
                self.scenarios.add(str(data['scenario']))
                self.index.extend((path, i) for i in range(len(data['policy'])))
        if not self.index:
            raise ValueError(f'No episode shards: {directory}')
        self.cached_path, self.cache = None, None

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        path, row = self.index[index]
        if path != self.cached_path:
            with np.load(path, allow_pickle=False) as data:
                self.cache = {k: data[k] for k in ('tokens', 'roles', 'global_state', 'legal', 'loss_mask', 'policy', 'value')}
            self.cached_path = path
        return {key: torch.from_numpy(value[row].copy()) for key, value in self.cache.items()}


def batch_loss(model, batch):
    logits, value_logits = model(batch['tokens'], batch['roles'], batch['global_state'], batch['legal'])
    scores = logits.masked_fill(~batch['loss_mask'], -1e9)
    policy_loss = -(batch['policy'] * F.log_softmax(scores, dim=-1)).sum(-1).mean()
    targets = batch['value']
    categories_loss = F.binary_cross_entropy_with_logits(value_logits[:, :8], targets[:, :8])
    rank_loss = F.smooth_l1_loss(value_logits[:, 8].sigmoid(), targets[:, 8])
    events_loss = F.binary_cross_entropy_with_logits(value_logits[:, 9:], targets[:, 9:])
    loss = policy_loss + categories_loss + rank_loss + .25 * events_loss
    metrics = {
        'loss': float(loss.detach()), 'policy_loss': float(policy_loss.detach()),
        'top1_agreement': float((scores.argmax(-1) == batch['policy'].argmax(-1)).float().mean()),
        'category_mae': float((value_logits[:, :8].sigmoid() - targets[:, :8]).abs().mean().detach()),
        'rank_mae': float((value_logits[:, 8].sigmoid() - targets[:, 8]).abs().mean().detach()),
    }
    return loss, metrics


def fit(config, data_path, output, provenance, warm_start=None, replay=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    train = Episodes(Path(data_path) / 'train')
    validation = Episodes(Path(data_path) / 'validation')
    if train.scenarios & validation.scenarios:
        raise ValueError('Train/validation episode leakage')
    sampler_weights = None
    if replay:
        old = Episodes(Path(replay) / 'train')
        if old.scenarios & validation.scenarios:
            raise ValueError('Replay/validation episode leakage')
        # Preserve imitation with a 50/50 old/new state sampling mixture.
        sampler_weights = [1 / len(train)] * len(train) + [1 / len(old)] * len(old)
        train = ConcatDataset((train, old))
    settings = config['training']
    device = resolve_device(settings['device'])
    torch.set_num_threads(2)
    torch.manual_seed(config['seed'])
    model = PolicyValue(**config['model'], team_count=config['team_count']).to(device)
    if warm_start:
        model.load_state_dict(NeuralPolicy(warm_start).model.state_dict())
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings['learning_rate'], weight_decay=.01)
    latest = output / 'last.pt'
    start, best, stale, history = 0, float('inf'), 0, []
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=True)
        if saved['provenance'] != provenance:
            raise ValueError('Training inputs changed')
        model.load_state_dict(saved['model'])
        optimizer.load_state_dict(saved['optimizer'])
        start, best, stale, history = saved['epoch'], saved['best'], saved['stale'], saved['history']
    if (output / 'complete.json').exists():
        return
    validation_loader = DataLoader(validation, batch_size=settings['batch_size'], shuffle=False)
    for epoch in range(start, settings['epochs']):
        if stale >= settings['patience']:
            break
        generator = torch.Generator().manual_seed(config['seed'] + epoch)
        sampler = WeightedRandomSampler(sampler_weights, num_samples=len(train), replacement=True, generator=generator) if sampler_weights else None
        loader = DataLoader(train, batch_size=settings['batch_size'], shuffle=sampler is None, sampler=sampler, generator=generator)
        model.train()
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            loss, _ = batch_loss(model, batch)
            if not torch.isfinite(loss):
                raise FloatingPointError('Non-finite policy/value loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        model.eval()
        sums, count = {}, 0
        with torch.inference_mode():
            for batch in validation_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                _, metrics = batch_loss(model, batch)
                n = len(batch['policy'])
                count += n
                for key, value in metrics.items():
                    sums[key] = sums.get(key, 0) + value * n
        metrics = {key: value / count for key, value in sums.items()}
        history.append({'epoch': epoch + 1, **metrics})
        improved = metrics['loss'] < best - 1e-4
        best, stale = (metrics['loss'], 0) if improved else (best, stale + 1)
        checkpoint = {'model': model.state_dict(), 'spec': model.spec, 'provenance': provenance}
        if improved:
            atomic_torch(output / 'best.pt', checkpoint)
        atomic_torch(latest, {**checkpoint, 'optimizer': optimizer.state_dict(), 'epoch': epoch + 1, 'best': best, 'stale': stale, 'history': history})
        print(json.dumps({'epoch': epoch + 1, 'device': device, **metrics}), flush=True)
    atomic_json(output / 'complete.json', {'provenance': provenance, 'epochs': len(history), 'history': history, 'best_validation_loss': best})
