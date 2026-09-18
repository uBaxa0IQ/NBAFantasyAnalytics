"""Universal category-conditioned draft policy/value network and V7 migration."""
from __future__ import annotations

import os
from pathlib import Path

import torch
from torch import nn

from .v7_state import CATEGORIES as V7_CATEGORIES, GLOBAL_DIM as V7_GLOBAL_DIM, POSITIONS as V7_POSITIONS, STATS as V7_STATS
from .v8_state import CATEGORY_TO_ID, CATEGORY_VOCAB, GLOBAL_DIM, POSITIONS, RAW_DIM, RAW_STATS


class UniversalPolicyValue(nn.Module):
    def __init__(self, width=96, heads=4, layers=2, max_team_count=16):
        super().__init__()
        self.spec = {'width': width, 'heads': heads, 'layers': layers, 'max_team_count': max_team_count,
                     'category_vocab': list(CATEGORY_VOCAB)}
        self.raw_project = nn.Linear(RAW_DIM, width)
        self.category_value_embedding = nn.Embedding(len(CATEGORY_VOCAB) + 1, width, padding_idx=len(CATEGORY_VOCAB))
        self.category_meta_project = nn.Linear(2, width, bias=False)
        self.category_context_gate = nn.Parameter(torch.zeros(()))
        self.role = nn.Embedding(max_team_count + 1, width)
        self.global_project = nn.Linear(GLOBAL_DIM, width)
        layer = nn.TransformerEncoderLayer(width, heads, width * 2, dropout=0.0, batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.policy = nn.Sequential(nn.Linear(width * 2, width), nn.GELU(), nn.Linear(width, 1))
        self.value_hidden = nn.Sequential(nn.Linear(width, width), nn.GELU())
        self.category_output_weight = nn.Embedding(len(CATEGORY_VOCAB) + 1, width, padding_idx=len(CATEGORY_VOCAB))
        self.category_output_bias = nn.Embedding(len(CATEGORY_VOCAB) + 1, 1, padding_idx=len(CATEGORY_VOCAB))
        self.event_output = nn.Linear(width, 3)

    def forward(self, raw, category_values, category_ids, category_meta, category_mask, roles, global_state, legal):
        if not legal.any(dim=1).all():
            raise ValueError('Every state must contain a legal action')
        if int(roles.max()) > self.spec['max_team_count']:
            raise ValueError('Team count exceeds model capacity')
        category_embedding = self.category_value_embedding(category_ids)
        effective_values = category_values * category_meta[:, None, :, 0] * category_mask[:, None, :]
        contribution = torch.einsum('bpc,bcw->bpw', effective_values, category_embedding)
        player = self.raw_project(raw) + contribution + self.role(roles)
        descriptor = category_embedding + self.category_meta_project(category_meta)
        denominator = category_mask.sum(1, keepdim=True).clamp_min(1).to(descriptor.dtype)
        category_context = (descriptor * category_mask.unsqueeze(-1)).sum(1) / denominator
        cls = self.global_project(global_state) + self.category_context_gate * category_context
        encoded = self.encoder(torch.cat((cls.unsqueeze(1), player), dim=1))
        context = encoded[:, 0]
        logits = self.policy(torch.cat((encoded[:, 1:], context[:, None].expand(-1, raw.shape[1], -1)), dim=-1)).squeeze(-1)
        logits = logits.masked_fill(~legal, -1e9)
        hidden = self.value_hidden(context)
        category_logits = torch.einsum('bw,bcw->bc', hidden, self.category_output_weight(category_ids))
        category_logits = category_logits + self.category_output_bias(category_ids).squeeze(-1)
        category_logits = category_logits.masked_fill(~category_mask, 0.0)
        return logits, category_logits, self.event_output(hidden)


class UniversalResidualPolicyValue(nn.Module):
    """Frozen universal base plus a small league-conditioned residual adapter.

    A zero adapter scale is exactly the source policy.  The adapter deliberately
    consumes only portable league/player descriptors: it has no player, format or
    opponent-family ids, so a selected checkpoint can interpolate to unseen league
    sizes and category combinations.
    """
    def __init__(self, base_spec, adapter_width=32, adapter_scale=1.0):
        super().__init__()
        clean = dict(base_spec); clean.pop('category_vocab', None); clean.pop('architecture', None)
        self.base = UniversalPolicyValue(**clean)
        self.adapter_width = int(adapter_width)
        self.adapter_scale = float(adapter_scale)
        self.raw_adapter = nn.Linear(RAW_DIM, self.adapter_width)
        self.category_adapter = nn.Embedding(len(CATEGORY_VOCAB) + 1, self.adapter_width,
                                             padding_idx=len(CATEGORY_VOCAB))
        self.category_meta_adapter = nn.Linear(2, self.adapter_width, bias=False)
        self.role_adapter = nn.Embedding(clean.get('max_team_count', 16) + 1, self.adapter_width)
        self.global_adapter = nn.Linear(GLOBAL_DIM, self.adapter_width)
        self.policy_adapter = nn.Sequential(
            nn.Linear(self.adapter_width * 3, self.adapter_width), nn.GELU(), nn.Linear(self.adapter_width, 1))
        self.value_adapter = nn.Sequential(
            nn.Linear(self.adapter_width * 2, self.adapter_width), nn.GELU())
        self.category_value_adapter = nn.Embedding(len(CATEGORY_VOCAB) + 1, self.adapter_width,
                                                   padding_idx=len(CATEGORY_VOCAB))
        self.category_bias_adapter = nn.Embedding(len(CATEGORY_VOCAB) + 1, 1,
                                                  padding_idx=len(CATEGORY_VOCAB))
        self.event_adapter = nn.Linear(self.adapter_width, 3)
        self.spec = {'architecture': 'universal_residual_v1', 'base_spec': dict(base_spec),
                     'adapter_width': self.adapter_width}
        self.reset_adapter()

    def reset_adapter(self):
        # Exact source parity at initialization while retaining gradients through
        # the output layers after the first optimizer update.
        nn.init.zeros_(self.policy_adapter[-1].weight); nn.init.zeros_(self.policy_adapter[-1].bias)
        nn.init.zeros_(self.category_value_adapter.weight)
        nn.init.zeros_(self.category_bias_adapter.weight)
        nn.init.zeros_(self.event_adapter.weight); nn.init.zeros_(self.event_adapter.bias)

    def freeze_base(self):
        self.base.requires_grad_(False)
        self.base.eval()
        return self

    def train(self, mode=True):
        super().train(mode)
        # The source model is a fixed teacher even while adapters are fitted.
        self.base.eval()
        return self

    def adapter_parameters(self):
        return (parameter for name, parameter in self.named_parameters() if not name.startswith('base.'))

    def forward(self, raw, category_values, category_ids, category_meta, category_mask, roles, global_state, legal):
        base_logits, base_categories, base_events = self.base(
            raw, category_values, category_ids, category_meta, category_mask, roles, global_state, legal)
        effective = category_values * category_meta[:, None, :, 0] * category_mask[:, None, :]
        category_tokens = self.category_adapter(category_ids) + self.category_meta_adapter(category_meta)
        player = self.raw_adapter(raw) + torch.einsum('bpc,bcw->bpw', effective, category_tokens)
        player = player + self.role_adapter(roles)
        denominator = category_mask.sum(1, keepdim=True).clamp_min(1).to(category_tokens.dtype)
        category_context = (category_tokens * category_mask.unsqueeze(-1)).sum(1) / denominator
        global_context = self.global_adapter(global_state)
        context = global_context + category_context
        residual_logits = self.policy_adapter(torch.cat(
            (player, context[:, None].expand(-1, raw.shape[1], -1),
             global_context[:, None].expand(-1, raw.shape[1], -1)), dim=-1)).squeeze(-1)
        residual_logits = residual_logits.masked_fill(~legal, 0.0)
        pooled = (player * legal.unsqueeze(-1)).sum(1) / legal.sum(1, keepdim=True).clamp_min(1)
        hidden = self.value_adapter(torch.cat((pooled, context), dim=-1))
        residual_categories = torch.einsum('bw,bcw->bc', hidden, self.category_value_adapter(category_ids))
        residual_categories += self.category_bias_adapter(category_ids).squeeze(-1)
        residual_categories = residual_categories.masked_fill(~category_mask, 0.0)
        scale = self.adapter_scale
        return (base_logits + scale * residual_logits,
                base_categories + scale * residual_categories,
                base_events + scale * self.event_adapter(hidden))


def migrate_v7_checkpoint(source, destination, provenance):
    payload = torch.load(source, map_location='cpu', weights_only=True)
    old = payload['model']; spec = payload['spec']
    model = UniversalPolicyValue(width=spec['width'], heads=spec['heads'], layers=spec['layers'])
    with torch.no_grad():
        model.raw_project.weight.zero_(); model.raw_project.bias.copy_(old['project.bias'])
        for old_index, name in enumerate((*V7_STATS, *V7_POSITIONS), start=len(V7_CATEGORIES)):
            new_index = RAW_STATS.index(name) if name in RAW_STATS else len(RAW_STATS) + POSITIONS.index(name)
            model.raw_project.weight[:, new_index].copy_(old['project.weight'][:, old_index])
        model.category_value_embedding.weight.zero_()
        for index, category in enumerate(V7_CATEGORIES):
            model.category_value_embedding.weight[CATEGORY_TO_ID[category]].copy_(old['project.weight'][:, index])
        model.category_meta_project.weight.zero_(); model.category_context_gate.zero_()
        model.role.weight.zero_(); model.role.weight[:old['role.weight'].shape[0]].copy_(old['role.weight'])
        model.global_project.weight.zero_(); model.global_project.bias.copy_(old['global_project.bias'])
        model.global_project.weight[:, :V7_GLOBAL_DIM].copy_(old['global_project.weight'])
        encoder = {key.removeprefix('encoder.'): value for key, value in old.items() if key.startswith('encoder.')}
        model.encoder.load_state_dict(encoder)
        policy = {key.removeprefix('policy.'): value for key, value in old.items() if key.startswith('policy.')}
        model.policy.load_state_dict(policy)
        model.value_hidden[0].weight.copy_(old['value.0.weight']); model.value_hidden[0].bias.copy_(old['value.0.bias'])
        model.category_output_weight.weight.zero_(); model.category_output_bias.weight.zero_()
        for index, category in enumerate(V7_CATEGORIES):
            category_id = CATEGORY_TO_ID[category]
            model.category_output_weight.weight[category_id].copy_(old['value.2.weight'][index])
            model.category_output_bias.weight[category_id, 0].copy_(old['value.2.bias'][index])
        model.event_output.weight.copy_(old['value.2.weight'][len(V7_CATEGORIES):])
        model.event_output.bias.copy_(old['value.2.bias'][len(V7_CATEGORIES):])
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    torch.save({'model': model.state_dict(), 'spec': model.spec, 'provenance': provenance,
                'source_checkpoint_sha256': _sha(source), 'migration': 'exact-standard8-v1'}, temporary)
    os.replace(temporary, destination)
    return destination


def _sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class UniversalPolicy:
    def __init__(self, checkpoint, device='cpu'):
        payload = torch.load(checkpoint, map_location='cpu', weights_only=True)
        vocabulary = payload['spec'].get('category_vocab')
        if payload['spec'].get('architecture') == 'universal_residual_v1':
            vocabulary = payload['spec'].get('base_spec', {}).get('category_vocab')
        if vocabulary != list(CATEGORY_VOCAB):
            raise ValueError('Checkpoint category vocabulary/order is incompatible')
        spec = dict(payload['spec'])
        if spec.get('architecture') == 'universal_residual_v1':
            self.model = UniversalResidualPolicyValue(spec['base_spec'], spec['adapter_width'],
                                                      payload.get('adapter_scale', 1.0)).to(device).eval()
        else:
            spec.pop('category_vocab', None)
            self.model = UniversalPolicyValue(**spec).to(device).eval()
        self.model.load_state_dict(payload['model'])
        self.device = torch.device(device)
        self.path = Path(checkpoint)

    @torch.inference_mode()
    def predict(self, state, legal=None):
        encoded = state.encode(legal)
        args = [torch.as_tensor(value, device=self.device).unsqueeze(0) for value in encoded]
        logits, category_logits, event_logits = self.model(*args)
        values = torch.cat((category_logits.sigmoid(), event_logits.sigmoid()), dim=1)
        return logits[0].cpu().numpy(), values[0].cpu().numpy()
