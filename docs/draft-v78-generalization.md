# V7.8 opponent-generalization gate

V7.7 established that V7.6's gain over the older V7 checkpoint repeats across
optimizer seeds, but it did not establish a gain against a synthetic opponent
rule absent from training. V7.8 changes only that axis before attempting a
league-universal architecture.

The V7.6 checkpoint is the warm start, policy baseline and direct paired control.
Six training families cover familiar strong/mixed arenas, random weighted category
preferences, variable top-k V6 choices, three-category specialists and per-seat
mixtures. Blind late-pick search samples this training distribution independently;
it never receives the actual opponent assignments. All early targets retain V7.6.

Training has 600 drafts and validation-data generation has 120 drafts. Four late
decisions per draft use 12 candidates x 8 rollouts plus a separate 4-rollout audit.
The training family is stored in every shard and audited before training.

The model-selection validation has 60 drafts in each of three conditions: familiar,
a linear roster-need proxy absent from training, and a projection-input shift. The
final holdout remains unopened unless familiar delta is at least -0.05 category and
proxy-generalization delta at least -0.03 category. After freezing the checkpoint,
the holdout has 80 drafts each for strong, mixed, nonlinear roster need, a market/
need/position hybrid and projection shift. Nonlinear need and hybrid are absent from
both training and validation. Seats and terminal randomness are paired.

V7.8 remains standard 8 categories, 10 teams and the same historical player
snapshot. Synthetic diversity is not all possible human behaviour. The two primary
category contrasts use Bonferroni-adjusted 97.5% intervals; other metrics are
exploratory. No model is promoted and no universal architecture is launched.

Dry/preflight: `python scripts/draft_v78_generalization.py`

Authorized launch: `powershell -NoExit -ExecutionPolicy Bypass -File scripts/run_draft_v78_generalization.ps1 -Execute`

The same command resumes compatible completed episodes, epochs and evaluation
scenarios. Expected total time is 14.5-19 hours, dominated by 720 search-generated
drafts. This estimate is calibrated from V7.6 and V7.7 rather than a promise.
