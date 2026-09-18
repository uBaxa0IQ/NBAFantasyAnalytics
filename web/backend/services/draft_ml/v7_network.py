"""Small set-attention policy/value network. Research only; no live registration."""
from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from torch import nn

from .v7_state import PLAYER_DIM, GLOBAL_DIM, CATEGORIES


class PolicyValue(nn.Module):
    def __init__(self, width=96, heads=4, layers=2, team_count=10):
        super().__init__()
        self.spec = dict(width=width, heads=heads, layers=layers, team_count=team_count)
        self.project = nn.Linear(PLAYER_DIM, width)
        self.role = nn.Embedding(team_count + 1, width)
        self.global_project = nn.Linear(GLOBAL_DIM, width)
        layer = nn.TransformerEncoderLayer(width, heads, width * 2, dropout=0.0, batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.policy = nn.Sequential(nn.Linear(width * 2, width), nn.GELU(), nn.Linear(width, 1))
        self.value = nn.Sequential(nn.Linear(width, width), nn.GELU(), nn.Linear(width, len(CATEGORIES) + 3))

    def forward(self, tokens, roles, global_state, legal):
        if not legal.any(dim=1).all():
            raise ValueError('Every state must contain a legal action')
        x = self.project(tokens) + self.role(roles)
        cls = self.global_project(global_state).unsqueeze(1)
        encoded = self.encoder(torch.cat((cls, x), dim=1))
        context = encoded[:, :1]
        logits = self.policy(torch.cat((encoded[:, 1:], context.expand(-1, tokens.shape[1], -1)), dim=-1)).squeeze(-1)
        logits = logits.masked_fill(~legal, -1e9)
        return logits, self.value(context.squeeze(1))


def atomic_torch(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    torch.save(payload, temporary)
    os.replace(temporary, path)


class NeuralPolicy:
    def __init__(self, checkpoint, device='cpu'):
        self.path = Path(checkpoint)
        payload = torch.load(self.path, map_location='cpu', weights_only=True)
        self.device = torch.device(device)
        self.model = PolicyValue(**payload['spec']).to(self.device).eval()
        self.model.load_state_dict(payload['model'])

    @torch.inference_mode()
    def predict(self, state, legal=None):
        encoded = state.encode(legal)
        args = [torch.as_tensor(x, device=self.device).unsqueeze(0) for x in encoded]
        logits, values = self.model(*args)
        return logits[0].cpu().numpy(), values[0].sigmoid().cpu().numpy()


def resolve_device(requested):
    if requested == 'auto':
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    if requested == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA explicitly requested but unavailable')
    return requested
