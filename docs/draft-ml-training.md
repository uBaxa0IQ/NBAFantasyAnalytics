# Draft ML training pipeline

The pipeline is deliberately offline and opt-in. Importing the backend never generates data or trains a model. Every expensive or mutating CLI command requires `--execute`; without it the command prints its plan and exits.

## Stages

1. Generate counterfactual state/action rows through population self-play.
2. Split by complete scenario into train, validation, and test sets (80/10/10).
3. Train four value regressors and one candidate-ranking policy classifier.
4. Evaluate a frozen checkpoint on the untouched test split.
5. Benchmark the candidate policy against legacy policies in held-out projection stress.
6. Promote only when every metric and self-play gate passes.

Later iterations can generate new scenarios with a previous frozen policy in the self-play population. This is approximate policy iteration: the previous model controls adaptive continuations, while fresh counterfactual rollouts create improved action labels.

No weekly H2H season simulator is used.

## Data contract

Each JSONL row represents one candidate at one draft state. It includes:

- stable state and scenario identifiers;
- roster progress, market timing, positional feasibility, and strategy entropy;
- own and opponent category strength;
- candidate Z, raw stat, and projected marginal contribution per category;
- expected category wins, league rank, downside, composite reward, and best-action label.

All decisions from one simulated draft stay in the same split, preventing adjacent picks from leaking between training and evaluation.

## Installation

```powershell
pip install -r requirements-ml.txt
```

## Safe dry runs

These commands do not generate or train anything because `--execute` is absent:

```powershell
python -m web.backend.services.draft_ml generate --config configs/draft_ml_standard8.json
python -m web.backend.services.draft_ml train --format standard8 --dataset artifacts/draft_ml/standard8/standard8-dataset.jsonl.gz --checkpoint artifacts/draft_ml/standard8/checkpoints/v1
python -m web.backend.services.draft_ml benchmark --format standard8 --checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --runs-per-slot 20 --output artifacts/draft_ml/standard8/self-play-v1.json
```

## Execution sequence

Run only after reviewing the dry-run plan:

```powershell
python -m web.backend.services.draft_ml generate --config configs/draft_ml_standard8.json --execute
python -m web.backend.services.draft_ml train --format standard8 --dataset artifacts/draft_ml/standard8/standard8-dataset.jsonl.gz --checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --execute
python -m web.backend.services.draft_ml evaluate --dataset artifacts/draft_ml/standard8/standard8-dataset.jsonl.gz --checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --output artifacts/draft_ml/standard8/test-v1.json --execute
python -m web.backend.services.draft_ml benchmark --format standard8 --checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --runs-per-slot 20 --output artifacts/draft_ml/standard8/self-play-v1.json --execute
python -m web.backend.services.draft_ml promote --format standard8 --checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --metrics artifacts/draft_ml/standard8/test-v1.json --self-play artifacts/draft_ml/standard8/self-play-v1.json --name standard8-v1 --execute
```

Use `configs/draft_ml_custom11.json` and parallel artifact paths for the 11-category model.

## Iterative self-play

Never continue training in place. Generate a new immutable dataset from the previous frozen checkpoint, train a new checkpoint, and repeat all test and promotion gates:

```powershell
python -m web.backend.services.draft_ml generate --config configs/draft_ml_standard8.json --policy-checkpoint artifacts/draft_ml/standard8/checkpoints/v1 --output artifacts/draft_ml/standard8/standard8-dataset-v2.jsonl.gz --execute
python -m web.backend.services.draft_ml train --format standard8 --dataset artifacts/draft_ml/standard8/standard8-dataset-v2.jsonl.gz --checkpoint artifacts/draft_ml/standard8/checkpoints/v2 --execute
```

Omit `--policy-checkpoint` for the first bootstrap dataset. Generation refuses to overwrite an existing dataset or its manifest.

## Promotion gates

A checkpoint is rejected unless all conditions pass:

- reward MAE is at most 0.55;
- policy top-1 accuracy is at least 35%;
- mean decision regret is at most 0.20;
- the lower bound of the paired self-play category-win interval is positive;
- worst-decile category wins do not materially regress.

Promotion creates a new immutable version directory and atomically updates `champions/<format>/current.json`. Existing champions are never overwritten. Evaluation and self-play reports must point to that exact checkpoint, and evaluation must use the untouched test split. The live backend remains on the heuristic adaptive policy until a champion exists; a promoted checkpoint becomes the optional final reranker after projected lookahead.

## Recommended first run

Start with a small smoke dataset (for example 20 episodes, 6 candidates, one rollout) to validate runtime and memory. Then scale in steps. Do not start the full configuration until fresh ESPN projections are available; otherwise the learned policy will encode previous-season fallback behavior.
