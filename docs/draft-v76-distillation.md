# V7.6 late-search distillation — prepared, NOT STARTED

First attempt to transfer useful blind late-search decisions into V7 weights.
No model-size increase, no production integration. Launch only on user command.

## Data and labels

400 training and 80 validation drafts, 10 teams/13 slots/8 categories. Within
each split, seats and strong/mixed arenas are balanced. New v76:760910 namespace.
All 13 own-pick states are retained (6,240 states total): early states preserve
frozen V7 iteration-2 policy; four late states per draft can receive search labels
(1,920 late decisions). No old holdout is used as training data.

Frozen V7 proposes original actions. Full blind search evaluates up to 12
candidates x 8 continuations. It does not receive actual opponent identities or
the real arena label. Best proposal and baseline receive four NEW paired audit
continuations. Change the played action only if mean utility advantage >=0.02.
This is a noisy engineering filter, NOT per-action statistical certification.

When accepted, target distribution blends 25% original-policy distribution with
75% search distribution across candidate scores. Search temperature 0.15; original
policy temperature 0.5. Only the selected action gets the extra audit; alternative
candidate probabilities are not individually certified. Rejected decisions keep
the old policy target. Full legal-action loss prevents the model from ignoring
unsearched legal alternatives. No oracle opponent labels enter search.

Less than 20 accepted training picks stops the pipeline BEFORE training. Value
targets are the actual completed trajectory's outcomes averaged over eight new
terminal perturbations. This attempt fine-tunes both policy and value with the
existing supervised loss. It does not freeze value weights, guarantee unchanged
early picks, or guarantee that every target is stronger than the old policy.

## Training

Warm-start exactly the saved V7 iteration-2 checkpoint. Same architecture and
feature dimensions. Learning rate 0.00003, batch 24, up to 12 epochs, patience 3,
CUDA when available. Early-state distillation is the retention mechanism; no
separate replay corpus or larger network in this first experiment.

Best checkpoint is chosen by validation loss. Whole drafts separate training
from validation. Checkpoints and optimizer resume at completed epoch boundaries.
Atomic JSON/NPZ/checkpoint writes retry temporary Windows file-access errors.
A blocked RUNNING heartbeat does not cancel the calculation.

## Evaluation and stop rules

100 validation and 200 holdout full-draft scenarios, each balanced across arenas
and seats, with disjoint seeds from data and previous experiments. Four arms:
old V7, new V7, old V7 + cheap blind search, new V7 + cheap blind search. Search
uses up to six candidates/three continuations on picks 10–13. New and old policies
each propose their own top candidates; opponent history always remains frozen.

If validation category delta new-vs-old < -0.10, stop before opening holdout.
Otherwise freeze checkpoint SHA and run holdout once. This gate avoids spending
on an obvious regression; passing is not a success claim. There is only one
training configuration, no automatic sweep or holdout-based selection.

Primary comparisons: new vs old without search and new-cheap vs old-cheap.
Two primary category contrasts use 97.5% marginal normal intervals (Bonferroni).
Rank/top4/top1 and per-arena results are exploratory. Also report new-without-
search vs old-cheap to inspect how much of the search benefit was transferred.
Do not claim noninferiority or full benefit transfer just because a CI spans zero.

## Time allowance

Based on V7.5 measured ~93 seconds per full-search pick and ~25 seconds per cheap
search pick under six CPU workers. Generation includes additional candidate audits.

- Generation: 9–14 hours.
- GPU training: 0.3–1.5 hours, depending on early stopping and data loading.
- Validation: 1–2 hours.
- Holdout: 2–3.5 hours.
- Whole cycle: approximately 13–21 hours (rounded planning range, not guarantee).

Hardware discovery/dry plan and small synthetic tests are allowed during
preparation. None of these are the real 480-draft data collection or training.

## Commands and files

Dry plan: `python scripts/draft_v76_distillation.py` (no run directory created).
Future visible launch: `scripts/run_draft_v76_distillation.ps1 -Execute`.
Output: `artifacts/draft_ml/standard8-v76-distillation`.

Detached coordinator writes status independently of console selection. Each
stage writes logs and generation/evaluation progress. Re-run the same launcher
to resume compatible completed episodes, epochs and stages. Fingerprint changes
refuse mixing; completed-stage checksums protect cached outputs. Closing the
viewer is not a stop command. Final statuses: COMPLETE, STOP_FOR_REVIEW, FAILED.
Both data and validation gates require user review; no automatic follow-up run.

Same historical snapshot and familiar synthetic policy families remain important
limitations. No weekly H2H, unseen-season or unknown-human-policy guarantee.
