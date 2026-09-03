"""Lazy scikit-learn value and policy model training/checkpointing."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path

from .dataset import read_records


VALUE_TARGETS = (
    "expected_category_wins", "expected_league_rank", "downside", "reward",
)


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


def _metric_report(
    records, matrix, vectorizer, value_models, policy_model, ml,
    policy_type="pointwise_v1",
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
    correct = 0
    regrets = []
    for indices in state_rows.values():
        selected = max(indices, key=lambda index: policy_probability[index])
        best = max(indices, key=lambda index: labels[index]["reward"])
        correct += int(selected == best)
        regrets.append(float(labels[best]["reward"] - labels[selected]["reward"]))
    return {
        "rows": len(records),
        "states": len(state_rows),
        "value": value_metrics,
        "policy": {
            "log_loss": float(ml["log_loss"](policy_truth, policy_probability, labels=[0, 1])),
            "top1_accuracy": correct / max(1, len(state_rows)),
            "mean_regret": sum(regrets) / max(1, len(regrets)),
        },
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
    metrics = _metric_report(
        validation, validation_matrix, vectorizer, value_models, policy_model, ml, policy_type,
    )

    checkpoint = Path(checkpoint_dir)
    if checkpoint.exists():
        raise FileExistsError(f"Checkpoint already exists: {checkpoint}")
    checkpoint.mkdir(parents=True)
    ml["joblib"].dump(vectorizer, checkpoint / "vectorizer.joblib")
    for target, model in value_models.items():
        ml["joblib"].dump(model, checkpoint / f"value_{target}.joblib")
    ml["joblib"].dump(policy_model, checkpoint / "policy.joblib")
    manifest = {
        "model_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(Path(dataset_path).resolve()),
        "random_seed": random_seed,
        "targets": list(VALUE_TARGETS),
        "policy_type": policy_type,
        "training_pairs": int(len(policy_labels)),
        "validation_metrics": metrics,
        "metadata": metadata or {},
    }
    (checkpoint / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


class DraftModelBundle:
    def __init__(self, checkpoint_dir):
        ml = _ml_imports()
        checkpoint = Path(checkpoint_dir)
        self.ml = ml
        self.manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
        self.policy_type = self.manifest.get("policy_type", "pointwise_v1")
        self.vectorizer = ml["joblib"].load(checkpoint / "vectorizer.joblib")
        self.value_models = {
            target: ml["joblib"].load(checkpoint / f"value_{target}.joblib")
            for target in VALUE_TARGETS
        }
        self.policy_model = ml["joblib"].load(checkpoint / "policy.joblib")

    def predict(self, records):
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


def evaluate_checkpoint(dataset_path, checkpoint_dir, split="test"):
    ml = _ml_imports()
    records = _load_split(dataset_path, split)
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
    )
