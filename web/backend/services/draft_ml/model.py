"""Lazy scikit-learn value and policy model training/checkpointing."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil

from .dataset import read_records


VALUE_TARGETS = (
    "expected_category_wins", "expected_league_rank", "downside", "reward",
)
MARKET_MODELS = ("conservative", "espn_draft", "league_rater", "category_z")


def _ml_imports():
    try:
        import joblib
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
        from sklearn.feature_extraction import DictVectorizer
        from sklearn.metrics import log_loss, mean_absolute_error, mean_squared_error
    except ImportError as error:
        raise RuntimeError(
            "ML dependencies are not installed. Run: pip install -r requirements-ml.txt"
        ) from error
    return {
        "joblib": joblib,
        "np": np,
        "Regressor": HistGradientBoostingRegressor,
        "Classifier": HistGradientBoostingClassifier,
        "Vectorizer": DictVectorizer,
        "mae": mean_absolute_error,
        "mse": mean_squared_error,
        "log_loss": log_loss,
    }


def _load_split(dataset_path, split):
    records = list(read_records(dataset_path, split))
    if not records:
        raise ValueError(f"Dataset split is empty: {split}")
    return records


def _state_groups(records):
    groups = {}
    for index, record in enumerate(records):
        groups.setdefault(record.get("state_id", "inference"), []).append(index)
    return groups


def _pairwise_training_data(records, matrix, np):
    differences, outcomes = [], []
    labels = [record["labels"] for record in records]
    for indices in _state_groups(records).values():
        for left_position, left in enumerate(indices):
            for right in indices[left_position + 1:]:
                delta = float(labels[left]["reward"]) - float(labels[right]["reward"])
                if abs(delta) <= 1e-12:
                    continue
                difference = matrix[left] - matrix[right]
                outcome = int(delta > 0)
                # Mirrored pairs keep classes exactly balanced and make the
                # learned preference invariant to candidate ordering.
                differences.extend((difference, -difference))
                outcomes.extend((outcome, 1 - outcome))
    if not differences:
        raise ValueError("No non-tied candidate pairs in training split")
    return np.vstack(differences), np.asarray(outcomes)


def _policy_scores(records, matrix, policy_model, policy_type, np):
    if policy_type != "pairwise_v2":
        return policy_model.predict_proba(matrix)[:, 1]
    scores = np.ones(len(records), dtype=float)
    for indices in _state_groups(records).values():
        if len(indices) < 2:
            scores[indices[0]] = 1.0
            continue
        pairs, locations = [], []
        for left_position, left in enumerate(indices):
            for right in indices[left_position + 1:]:
                pairs.append(matrix[left] - matrix[right])
                locations.append((left, right))
        probabilities = policy_model.predict_proba(np.vstack(pairs))[:, 1]
        totals = {index: 0.0 for index in indices}
        for probability, (left, right) in zip(probabilities, locations):
            totals[left] += float(probability)
            totals[right] += 1.0 - float(probability)
        denominator = max(1, len(indices) - 1)
        for index in indices:
            scores[index] = totals[index] / denominator
    return scores


def _rerank_scores(records, reward_predictions, policy_scores, reward_weight, np):
    scores = np.zeros(len(records), dtype=float)
    for indices in _state_groups(records).values():
        rewards = np.asarray([reward_predictions[index] for index in indices], dtype=float)
        scale = float(rewards.std()) or 1.0
        normalized = (rewards - float(rewards.mean())) / scale
        for position, index in enumerate(indices):
            scores[index] = (
                float(reward_weight) * float(normalized[position])
                + (1.0 - float(reward_weight)) * float(policy_scores[index])
            )
    return scores


def _ranking_metrics(records, scores):
    labels = [record["labels"] for record in records]
    groups = _state_groups(records)
    correct, regrets = 0, []
    for indices in groups.values():
        selected = max(indices, key=lambda index: scores[index])
        best = max(indices, key=lambda index: labels[index]["reward"])
        correct += int(selected == best)
        regrets.append(float(labels[best]["reward"] - labels[selected]["reward"]))
    return {
        "top1_accuracy": correct / max(1, len(groups)),
        "mean_regret": sum(regrets) / max(1, len(regrets)),
    }


def _tune_rerank_weight(records, reward_predictions, policy_scores, np):
    trials = []
    for reward_weight in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        scores = _rerank_scores(records, reward_predictions, policy_scores, reward_weight, np)
        trials.append({"reward_weight": reward_weight, **_ranking_metrics(records, scores)})
    best = min(
        trials,
        key=lambda row: (row["mean_regret"], -row["top1_accuracy"], abs(row["reward_weight"] - 0.5)),
    )
    return float(best["reward_weight"]), trials


def _metric_report(
    records, matrix, vectorizer, value_models, policy_model, ml,
    policy_type="pointwise_v1", rerank_reward_weight=None,
):
    np = ml["np"]
    labels = [record["labels"] for record in records]
    value_metrics = {}
    predictions = {}
    for target, model in value_models.items():
        truth = np.asarray([float(label[target]) for label in labels])
        predicted = model.predict(matrix)
        predictions[target] = predicted
        value_metrics[target] = {
            "mae": float(ml["mae"](truth, predicted)),
            "rmse": float(math.sqrt(ml["mse"](truth, predicted))),
        }
    policy_truth = np.asarray([int(label.get("is_best", 0)) for label in labels])
    policy_probability = _policy_scores(records, matrix, policy_model, policy_type, np)
    state_rows = _state_groups(records)
    policy_ranking = _ranking_metrics(records, policy_probability)
    reranker = None
    if rerank_reward_weight is not None:
        scores = _rerank_scores(
            records, predictions["reward"], policy_probability, rerank_reward_weight, np,
        )
        reranker = {
            "reward_weight": float(rerank_reward_weight),
            **_ranking_metrics(records, scores),
        }
    return {
        "rows": len(records),
        "states": len(state_rows),
        "value": value_metrics,
        "policy": {
            "log_loss": float(ml["log_loss"](policy_truth, policy_probability, labels=[0, 1])),
            **policy_ranking,
        },
        "reranker": reranker,
        "feature_count": len(vectorizer.feature_names_),
    }


def train_models(dataset_path, checkpoint_dir, *, random_seed=260902, metadata=None):
    """Train value regressors and a state-grouped pairwise ranking policy."""
    ml = _ml_imports()
    np = ml["np"]
    train = _load_split(dataset_path, "train")
    validation = _load_split(dataset_path, "validation")
    vectorizer = ml["Vectorizer"](sparse=False)
    train_matrix = vectorizer.fit_transform([record["features"] for record in train])
    validation_matrix = vectorizer.transform([record["features"] for record in validation])

    value_models = {}
    for target in VALUE_TARGETS:
        model = ml["Regressor"](
            learning_rate=0.055,
            max_iter=260,
            max_leaf_nodes=31,
            l2_regularization=0.15,
            random_state=random_seed,
        )
        model.fit(train_matrix, np.asarray([float(record["labels"][target]) for record in train]))
        value_models[target] = model

    policy_type = "pairwise_v2"
    pair_matrix, policy_labels = _pairwise_training_data(train, train_matrix, np)
    policy_model = ml["Classifier"](
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=31,
        l2_regularization=0.2,
        random_state=random_seed,
    )
    policy_model.fit(pair_matrix, policy_labels)
    validation_policy = _policy_scores(
        validation, validation_matrix, policy_model, policy_type, np,
    )
    validation_reward = value_models["reward"].predict(validation_matrix)
    rerank_reward_weight, rerank_trials = _tune_rerank_weight(
        validation, validation_reward, validation_policy, np,
    )
    metrics = _metric_report(
        validation, validation_matrix, vectorizer, value_models, policy_model, ml, policy_type,
        rerank_reward_weight,
    )

    checkpoint = Path(checkpoint_dir)
    if checkpoint.exists():
        raise FileExistsError(f"Checkpoint already exists: {checkpoint}")
    checkpoint.mkdir(parents=True)
    ml["joblib"].dump(vectorizer, checkpoint / "vectorizer.joblib")
    for target, model in value_models.items():
        ml["joblib"].dump(model, checkpoint / f"value_{target}.joblib")
    ml["joblib"].dump(policy_model, checkpoint / "policy.joblib")
    artifact_names = ["vectorizer.joblib", "policy.joblib", *(
        f"value_{target}.joblib" for target in VALUE_TARGETS
    )]
    manifest = {
        "model_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(Path(dataset_path).resolve()),
        "random_seed": random_seed,
        "targets": list(VALUE_TARGETS),
        "policy_type": policy_type,
        "training_pairs": int(len(policy_labels)),
        "dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
        "feature_schema_version": 2,
        "rerank_reward_weight": rerank_reward_weight,
        "rerank_validation_trials": rerank_trials,
        "validation_metrics": metrics,
        "metadata": metadata or {},
        "artifact_sha256": {
            name: hashlib.sha256((checkpoint / name).read_bytes()).hexdigest()
            for name in artifact_names
        },
    }
    (checkpoint / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def train_market_expert(
    dataset_path, base_checkpoint_dir, checkpoint_dir, market_model,
    *, random_seed=260905, metadata=None,
):
    """Train one policy-only expert without reusing the inspected test split."""
    if market_model not in MARKET_MODELS:
        raise ValueError(f"Unsupported expert market: {market_model}")
    ml = _ml_imports()
    np = ml["np"]
    dataset_path = Path(dataset_path)
    base_checkpoint = Path(base_checkpoint_dir)
    base = DraftModelBundle(base_checkpoint)
    if base.manifest.get("dataset_sha256") != hashlib.sha256(dataset_path.read_bytes()).hexdigest():
        raise ValueError("Base checkpoint and expert dataset do not match")
    train = [row for row in _load_split(dataset_path, "train") if row.get("market_model") == market_model]
    validation = [
        row for row in _load_split(dataset_path, "validation")
        if row.get("market_model") == market_model
    ]
    if not train or not validation:
        raise ValueError(f"Dataset has no complete {market_model} train/validation split")
    train_matrix = base.vectorizer.transform([row["features"] for row in train])
    validation_matrix = base.vectorizer.transform([row["features"] for row in validation])
    pair_matrix, pair_labels = _pairwise_training_data(train, train_matrix, np)
    expert_policy = ml["Classifier"](
        learning_rate=0.05,
        max_iter=300,
        max_leaf_nodes=31,
        l2_regularization=0.2,
        random_state=random_seed,
    )
    expert_policy.fit(pair_matrix, pair_labels)
    expert_metrics = _metric_report(
        validation, validation_matrix, base.vectorizer, base.value_models,
        expert_policy, ml, "pairwise_v2", 0.0,
    )
    base_metrics = _metric_report(
        validation, validation_matrix, base.vectorizer, base.value_models,
        base.policy_model, ml, base.policy_type, 0.0,
    )

    checkpoint = Path(checkpoint_dir)
    if checkpoint.exists():
        raise FileExistsError(f"Checkpoint already exists: {checkpoint}")
    checkpoint.mkdir(parents=True)
    copied = ["vectorizer.joblib", *(f"value_{target}.joblib" for target in VALUE_TARGETS)]
    for name in copied:
        shutil.copy2(base_checkpoint / name, checkpoint / name)
    ml["joblib"].dump(expert_policy, checkpoint / "policy.joblib")
    artifact_names = [*copied, "policy.joblib"]
    manifest = {
        "model_version": 4,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path.resolve()),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "base_checkpoint": str(base_checkpoint.resolve()),
        "base_checkpoint_manifest_sha256": hashlib.sha256(
            (base_checkpoint / "manifest.json").read_bytes()
        ).hexdigest(),
        "random_seed": random_seed,
        "targets": list(VALUE_TARGETS),
        "policy_type": "pairwise_v2",
        "expert_market": market_model,
        "training_rows": len(train),
        "training_pairs": int(len(pair_labels)),
        "feature_schema_version": base.manifest.get("feature_schema_version", 2),
        "rerank_reward_weight": 0.0,
        "validation_metrics": expert_metrics,
        "base_validation_metrics_same_market": base_metrics,
        "metadata": {**base.manifest.get("metadata", {}), **(metadata or {})},
        "artifact_sha256": {
            name: hashlib.sha256((checkpoint / name).read_bytes()).hexdigest()
            for name in artifact_names
        },
    }
    (checkpoint / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class DraftModelBundle:
    def __init__(self, checkpoint_dir):
        checkpoint = Path(checkpoint_dir)
        self.manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
        for name, expected in (self.manifest.get("artifact_sha256") or {}).items():
            actual = hashlib.sha256((checkpoint / name).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"Checkpoint artifact checksum mismatch: {name}")
        self.policy_type = self.manifest.get("policy_type", "pointwise_v1")
        self.market_free_genome = None
        self.market_free_genomes = None
        if self.policy_type in {"market_free_linear_v1", "market_free_ensemble_v1"}:
            self.ml = None
            self.rerank_reward_weight = 0.0
            if self.policy_type == "market_free_ensemble_v1":
                self.market_free_genomes = json.loads(
                    (checkpoint / "genomes.json").read_text(encoding="utf-8")
                )
                if not isinstance(self.market_free_genomes, list) or not self.market_free_genomes:
                    raise ValueError("Market-free ensemble contains no genomes")
            else:
                self.market_free_genome = json.loads(
                    (checkpoint / "genome.json").read_text(encoding="utf-8")
                )
            self.vectorizer = None
            self.value_models = {}
            self.policy_model = None
            return
        ml = _ml_imports()
        self.ml = ml
        self.rerank_reward_weight = float(self.manifest.get("rerank_reward_weight", 0.72))
        self.vectorizer = ml["joblib"].load(checkpoint / "vectorizer.joblib")
        self.value_models = {
            target: ml["joblib"].load(checkpoint / f"value_{target}.joblib")
            for target in VALUE_TARGETS
        }
        self.policy_model = ml["joblib"].load(checkpoint / "policy.joblib")

    def predict(self, records):
        if self.market_free_genome is not None or self.market_free_genomes is not None:
            raise TypeError("Market-free policy requires full draft context")
        matrix = self.vectorizer.transform([record["features"] for record in records])
        policy = _policy_scores(
            records, matrix, self.policy_model, self.policy_type, self.ml["np"],
        )
        values = {target: model.predict(matrix) for target, model in self.value_models.items()}
        return [
            {
                "candidate_id": record.get("candidate_id"),
                "candidate_name": record.get("candidate_name"),
                "policy_probability": float(policy[index]),
                **{target: float(prediction[index]) for target, prediction in values.items()},
            }
            for index, record in enumerate(records)
        ]


def evaluate_checkpoint(dataset_path, checkpoint_dir, split="test", market_model=None):
    ml = _ml_imports()
    records = _load_split(dataset_path, split)
    if market_model is not None:
        records = [record for record in records if record.get("market_model") == market_model]
        if not records:
            raise ValueError(f"Dataset split has no rows for market: {market_model}")
    checkpoint = Path(checkpoint_dir)
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    vectorizer = ml["joblib"].load(checkpoint / "vectorizer.joblib")
    value_models = {
        target: ml["joblib"].load(checkpoint / f"value_{target}.joblib")
        for target in VALUE_TARGETS
    }
    policy_model = ml["joblib"].load(checkpoint / "policy.joblib")
    matrix = vectorizer.transform([record["features"] for record in records])
    return _metric_report(
        records, matrix, vectorizer, value_models, policy_model, ml,
        manifest.get("policy_type", "pointwise_v1"),
        manifest.get("rerank_reward_weight", 0.72),
    )
