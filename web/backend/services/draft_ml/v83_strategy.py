"""Distributional punt-strategy model trained on adaptive rollout labels."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from .v8_state import CATEGORY_VOCAB
from .v82_strategy import STRATEGY_FEATURES, STRATEGY_GLOBAL


class DistributionalStrategyScorer(nn.Module):
    """Format-routed rank and probability-over-no-punt heads."""

    def __init__(self, width=72, heads=4, layers=2, experts=4):
        super().__init__()
        self.width = int(width); self.heads = int(heads); self.layers = int(layers); self.experts = int(experts)
        self.category = nn.Embedding(len(CATEGORY_VOCAB), width)
        self.state = nn.Sequential(nn.Linear(6, width), nn.GELU(), nn.Linear(width, width))
        self.binding = nn.Sequential(nn.Linear(width * 2 + 1, width), nn.GELU(), nn.Linear(width, width))
        layer = nn.TransformerEncoderLayer(width, heads, width * 3, dropout=.06,
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.global_project = nn.Sequential(nn.Linear(STRATEGY_GLOBAL, width), nn.GELU(), nn.Linear(width, width))
        self.format_project = nn.Sequential(nn.Linear(4, width), nn.GELU(), nn.Linear(width, width))
        self.router = nn.Sequential(nn.Linear(width * 2, width), nn.GELU(), nn.Linear(width, experts))
        hidden_width = width * 5
        self.expert_heads = nn.ModuleList([
            nn.Sequential(nn.Linear(hidden_width, width), nn.GELU(), nn.Linear(width, 1)) for _ in range(experts)
        ])
        self.edge_heads = nn.ModuleList([
            nn.Sequential(nn.Linear(hidden_width, width), nn.GELU(), nn.Linear(width, 1)) for _ in range(experts)
        ])
        self.category_value = nn.Sequential(nn.Linear(width, width // 2), nn.GELU(), nn.Linear(width // 2, 1))
        self.spec = {"architecture": "universal_strategy_distributional_v1", "width": width,
                     "heads": heads, "layers": layers, "experts": experts,
                     "category_vocab": list(CATEGORY_VOCAB), "features": STRATEGY_FEATURES,
                     "global_features": STRATEGY_GLOBAL, "router_candidate_independent": True,
                     "outputs": ["rank_score", "probability_over_no_punt"]}

    def forward(self, features, mask, global_state):
        ids = torch.arange(len(CATEGORY_VOCAB), device=features.device)
        state_features = torch.cat((features[:, :, :5], features[:, :, 6:7]), dim=-1)
        base = self.category(ids)[None] + self.state(state_features)
        keep = features[:, :, 5:6]
        token = base + self.binding(torch.cat((base, base * (2 * keep - 1), keep), dim=-1))
        token = self.encoder(token, src_key_padding_mask=~mask)
        active = mask.unsqueeze(-1).to(token.dtype); kept = active * keep; punted = active * (1 - keep)
        denominator = active.sum(1).clamp_min(1)
        mean = (token * active).sum(1) / denominator
        kept_mean = (token * kept).sum(1) / kept.sum(1).clamp_min(1)
        punt_mean = (token * punted).sum(1) / punted.sum(1).clamp_min(1)
        maximum = token.masked_fill(~mask.unsqueeze(-1), -1e9).max(1).values
        global_hidden = self.global_project(global_state)
        hidden = torch.cat((mean, maximum, kept_mean, punt_mean, global_hidden), dim=-1)
        format_state = (base * active).sum(1) / denominator
        routing = F.softmax(self.router(torch.cat((format_state,
            self.format_project(global_state[:, :4])), dim=-1)), dim=-1)
        rank = torch.cat([head(hidden) for head in self.expert_heads], dim=-1)
        edge = torch.cat([head(hidden) for head in self.edge_heads], dim=-1)
        contribution = (self.category_value(token).squeeze(-1) * mask).sum(1) / mask.sum(1).clamp_min(1).sqrt()
        return (routing * rank).sum(-1) + contribution, (routing * edge).sum(-1)


def load_v3_warm_start(model, checkpoint):
    payload = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if payload["spec"].get("architecture") != "universal_strategy_v3":
        raise ValueError("V8.3 requires a V8.2.2 strategy-v3 warm start")
    missing, unexpected = model.load_state_dict(payload["model"], strict=False)
    if unexpected or any(not key.startswith("edge_heads.") for key in missing):
        raise ValueError(f"Incompatible warm start: missing={missing}, unexpected={unexpected}")
    return payload


class DistributionalStrategyEnsemble:
    def __init__(self, checkpoints, device="cpu"):
        self.models = []; self.device = torch.device(device)
        for checkpoint in checkpoints:
            payload = torch.load(checkpoint, map_location="cpu", weights_only=True); spec = payload["spec"]
            if spec.get("architecture") != "universal_strategy_distributional_v1":
                raise ValueError("V8.3 distributional checkpoint required")
            model = DistributionalStrategyScorer(spec["width"], spec["heads"], spec["layers"], spec["experts"])
            model.load_state_dict(payload["model"]); self.models.append(model.to(device).eval())

    @torch.inference_mode()
    def predict(self, features, masks, globals_):
        args = (torch.as_tensor(features, device=self.device), torch.as_tensor(masks, device=self.device),
                torch.as_tensor(globals_, device=self.device))
        scores, edges = [], []
        for model in self.models:
            score, edge = model(*args)
            scores.append((score - score.mean()) / score.std().clamp_min(1e-6))
            edges.append(edge.sigmoid())
        return torch.stack(scores).cpu().numpy(), torch.stack(edges).cpu().numpy()


class DistributionalStrategyDataset(Dataset):
    def __init__(self, directory, balance_exponent=0.0, maximum_multiplier=4.0):
        self.paths = sorted(Path(directory).glob("*.npz"))
        if not self.paths:
            raise ValueError(f"No distributional strategy shards: {directory}")
        self.scenarios = set(); keys = []
        for path in self.paths:
            with np.load(path, allow_pickle=False) as data:
                self.scenarios.add(str(data["scenario"])); profiles = json.loads(str(data["profiles"]))
                keys.append(f"{int(data['masks'][0].sum())}:{tuple(profiles[int(data['safe_index'])])}")
        counts = {key: keys.count(key) for key in set(keys)}
        raw = np.asarray([counts[key] ** (-float(balance_exponent)) for key in keys], dtype=np.float64)
        raw /= raw.mean(); self.sample_weights = np.minimum(raw, float(maximum_multiplier)); self.label_counts = counts

    def __len__(self): return len(self.paths)

    def __getitem__(self, index):
        with np.load(self.paths[index], allow_pickle=False) as data:
            keys = ("features", "masks", "globals", "utility_mean", "utility_std",
                    "best_probability", "edge_probability", "confirmed", "safe_index")
            return {key: torch.from_numpy(data[key].copy()) for key in keys}


def distributional_loss(model, row, settings):
    scores, edge_logits = model(row["features"], row["masks"], row["globals"])
    utilities = row["utility_mean"]
    target = (utilities - utilities.mean()) / utilities.std().clamp_min(1e-6)
    predicted = (scores - scores.mean()) / scores.std().clamp_min(1e-6)
    best_probability = row["best_probability"].clamp_min(settings["probability_floor"])
    best_probability = best_probability / best_probability.sum()
    listwise = -(best_probability * F.log_softmax(predicted / settings["prediction_temperature"], dim=0)).sum()
    confirmed = row["confirmed"].bool()
    edge = F.binary_cross_entropy_with_logits(edge_logits[confirmed], row["edge_probability"][confirmed])
    left, right = torch.triu_indices(len(scores), len(scores), offset=1, device=scores.device)
    pair_mask = confirmed[left] & confirmed[right]
    differences = target[left] - target[right]
    weights = differences.abs().clamp_min(.05).clamp_max(3.)
    pairwise_raw = F.softplus(settings["pairwise_margin"] -
                              differences.sign() * (predicted[left] - predicted[right])) * weights
    pairwise = pairwise_raw[pair_mask].sum() / weights[pair_mask].sum().clamp_min(1e-6)
    regression = F.smooth_l1_loss(predicted[confirmed], target[confirmed])
    loss = (settings["listwise_weight"] * listwise + settings["edge_weight"] * edge +
            settings["pairwise_weight"] * pairwise + settings["regression_weight"] * regression)
    winner = int(scores.argmax()); oracle = int(utilities.argmax())
    return loss, {"loss": float(loss.detach()), "listwise": float(listwise.detach()),
        "edge_brier": float(((edge_logits[confirmed].sigmoid() - row['edge_probability'][confirmed]) ** 2).mean().detach()),
        "pairwise": float(pairwise.detach()), "regression": float(regression.detach()),
        "top1": float(winner == oracle), "regret": float((utilities[oracle] - utilities[winner]).detach())}


def _atomic_torch(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.2)


def _atomic_json(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for attempt in range(21):
        try: os.replace(temporary, path); return
        except PermissionError:
            if attempt == 20: raise
            time.sleep(.2)


def fit_distributional_strategy(config, data, output, provenance, seed, warm_start):
    settings = config["training"]; output = Path(output); output.mkdir(parents=True, exist_ok=True)
    train = DistributionalStrategyDataset(Path(data) / "train", settings["balance_exponent"],
                                          settings["maximum_sample_multiplier"])
    validation = DistributionalStrategyDataset(Path(data) / "validation")
    if train.scenarios & validation.scenarios:
        raise ValueError("V8.3 train/validation leakage")
    device = ("cuda" if torch.cuda.is_available() else "cpu") if settings["device"] == "auto" else settings["device"]
    torch.manual_seed(seed); np.random.seed(seed % (2 ** 32))
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(seed)
    model = DistributionalStrategyScorer(settings["width"], settings["heads"], settings["layers"], settings["experts"])
    source = load_v3_warm_start(model, warm_start); model = model.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings["learning_rate"], weight_decay=settings["weight_decay"])
    latest = output / "last.pt"; start = 0; best = float("inf"); stale = 0; history = []
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=True)
        if saved["provenance"] != provenance or saved["seed"] != seed:
            raise ValueError("V8.3 training resume mismatch")
        model.load_state_dict(saved["model"]); optimizer.load_state_dict(saved["optimizer"])
        start, best, stale, history = saved["epoch"], saved["best"], saved["stale"], saved["history"]
    if (output / "complete.json").exists(): return
    for epoch in range(start, settings["epochs"]):
        if stale >= settings["patience"]: break
        generator = torch.Generator().manual_seed(seed + epoch)
        sampler = WeightedRandomSampler(train.sample_weights, len(train), replacement=True, generator=generator)
        model.train()
        for row in DataLoader(train, batch_size=None, sampler=sampler):
            row = {key: value.to(device) for key, value in row.items()}; optimizer.zero_grad(set_to_none=True)
            loss, _ = distributional_loss(model, row, settings)
            if not torch.isfinite(loss): raise FloatingPointError("Non-finite V8.3 loss")
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 1.0); optimizer.step()
        model.eval(); sums = {}; count = 0
        with torch.inference_mode():
            for row in DataLoader(validation, batch_size=None, shuffle=False):
                row = {key: value.to(device) for key, value in row.items()}
                _, metrics = distributional_loss(model, row, settings); count += 1
                for key, value in metrics.items(): sums[key] = sums.get(key, 0.0) + value
        metrics = {key: value / count for key, value in sums.items()}; history.append({"epoch": epoch + 1, **metrics})
        selection = metrics["loss"] + settings["validation_regret_weight"] * metrics["regret"]
        improved = selection < best - settings["minimum_improvement"]
        best, stale = (selection, 0) if improved else (best, stale + 1)
        checkpoint = {"model": model.state_dict(), "spec": model.spec, "provenance": provenance, "seed": seed,
                      "source_checkpoint_sha256": hashlib_sha(warm_start)}
        if improved: _atomic_torch(output / "best.pt", checkpoint)
        _atomic_torch(latest, {**checkpoint, "optimizer": optimizer.state_dict(), "epoch": epoch + 1,
                              "best": best, "stale": stale, "history": history})
        print(json.dumps({"seed": seed, "epoch": epoch + 1, "device": device, **metrics}), flush=True)
    _atomic_json(output / "complete.json", {"provenance": provenance, "seed": seed,
        "epochs": len(history), "best_selection": best, "history": history,
        "train_labels": train.label_counts})


def hashlib_sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
