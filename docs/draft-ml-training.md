# Draft ML training pipeline

## September 4 correction

Benchmark reports with `benchmark_version < 2` (including the old v1 A/B report)
must not be used as evidence of ML improvement over adaptive: the old dispatcher
silently routed `adaptive_heuristic` to ROTO. Version 2 explicitly dispatches every
optimizer and tests the actual called policy. Promotion rejects old reports.

ESPN `draftRanksByRankType.ROTO.rank` is a draft-market field, not the seasonal
Player Rater. Its league specificity has not been verified. `--market-model category_z`
is a separate, explicitly synthetic market ranked from the selected categories;
it is not a claim to reproduce ESPN. Run it alongside `espn_draft`, not as a replacement
for measured ADP. Both benchmarks must use the same `--input-snapshot`.

Use `scripts/run_draft_ml_standard8_resume_checked.ps1` for the current recovery.
It freezes future ESPN inputs, checkpoints each complete episode atomically, and
uses `--resume` to skip saved episodes after interruptions. Old recovery sources
are retained. Legacy episodes have no original raw-stat snapshot, so resumed training
is explicitly exploratory and cannot auto-promote. The script never deploys Docker.

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

## Market-free v6 research

`scripts/run_draft_ml_standard8_v6_1_pbt.ps1` runs the corrected population-based alternative without ADP, Player Rater, draft rank, or market labels as policy inputs. It evolves 24 linear policies for up to 96 generations against current policies, Hall of Fame policies, and fixed market-free anchors. Every generation champion is scored on an identical frozen validation arena, all champions are archived, and the best 12 across the complete history enter the final tournament. The old market scenarios remain external stress tests only. See `docs/draft-ml-v6-market-free-runbook.md` for the exact contract.

`scripts/run_draft_ml_standard8_v6_2_pbt.ps1` is the precommitted robustness phase: five independent multi-objective evolution seeds, category-build niche elites, per-seed diagnostics, and an equal-weight rank ensemble whose members are fixed before diagnostics. See `docs/draft-ml-v6-2-plan.md` for budgets, success gates, and the 2027 projections retraining contract.

`scripts/run_draft_ml_standard8_v6_3_meta.ps1` is the final linear-policy phase. It reuses all V6.2 generation archives, applies one common meta-validation arena, cross-play, pre-holdout weighted ensemble selection, and a new-seed paired holdout against the frozen V6.2 ensemble. No fresh population training is repeated. See `docs/draft-ml-v6-3-plan.md`.

## Data contract

Each JSONL row represents one candidate at one draft state. It includes:

- stable state and scenario identifiers;
- roster progress, market timing, positional feasibility, and strategy entropy;
- own and opponent category strength;
- candidate Z, raw stat, and projected marginal contribution per category;
- explicit market-source provenance (draft board, league Player Rater, fallback, conservative, or synthetic);
- expected category wins, league rank, downside, composite reward, and best-action label.

All decisions from one simulated draft stay in the same split, preventing adjacent picks from leaking between training and evaluation. Market-v4 also uses an exact 80/10/10 split inside every market/opponent cell.

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
- live blended reranker top-1 accuracy is at least 35%;
- live blended reranker mean decision regret is at most 0.20;
- the lower bound of the paired self-play category-win interval is positive;
- worst-decile category wins do not materially regress.

Promotion creates a new immutable version directory and atomically updates `champions/<format>/current.json`. Existing champions are never overwritten. Evaluation and self-play reports must point to that exact checkpoint, and evaluation must use the untouched test split. The live backend remains on the heuristic adaptive policy until a champion exists; a promoted checkpoint becomes the optional final reranker after projected lookahead.

A checkpoint trained entirely on `previous_season` fallback stats is marked in its manifest and cannot be promoted. It remains useful for structural research, but live promotion requires at least actual `selected_period` projections and fresh evaluation.

## Recommended first run

Start with a small smoke dataset (for example 20 episodes, 6 candidates, one rollout) to validate runtime and memory. Then scale in steps. Do not start the full configuration until fresh ESPN projections are available; otherwise the learned policy will encode previous-season fallback behavior.
# League market v3 (2026-09-04)

V7 research preparation and launch/resume instructions are documented in
[draft-ml-v7-plan.md](draft-ml-v7-plan.md). V7 is not connected to live picks.

`espn_roto_rank` remains the ESPN draft board. `espn_league_rater_rank`
comes separately from league-response `ratings.0.totalRanking`, with league,
season and category provenance. Bucket 0 is ESPN's default: its match to the
user-selected Player Rater period has NOT been verified. Do not describe it as
an exact copy of a screenshot or as a projected rating.

Live availability uses the earlier of draft-board and compatible league-rater
prices (each blended with ADP). This conservative guard prevents a late rater
rank from making an early draft-board player appear safe to wait for. It can
overestimate demand; it is not a calibrated prediction of human picks. Punt
choices do not change the market. Category mismatches discard the league rater;
missing/invalid ratings fall back to draft rank/ADP. The API and UI disclose this.

`scripts/run_draft_ml_standard8_market_v3.ps1` starts an isolated 240-episode
8-cat dataset and resumes only its own atomic episode journal. v2 files are
preserved, not mixed into v3. Teacher generation uses the heuristic, not the
old-market learned checkpoint. The frozen v3 input contains 300 players,
265 with league-response rater values; remaining players use draft fallback.
After training/testing, the script runs four paired A/B market scenarios:
conservative (live rule), ESPN draft, league rater with explicit fallback, and
synthetic category Z. These test sensitivity, not historical human behavior.
No automatic ML promotion. Exact UI-period matching and empirical calibration
remain open validation items, not solved by these code changes.
