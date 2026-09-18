# V7: policy/value research, prepared 2026-09-08

Status: code prepared; no real V7 training started. Research only, no live
integration or automatic promotion. First experiment: standard 8 categories,
10 teams, 13 players. Config: `configs/draft_ml_v7.json`.

## Why move beyond V6 without discarding it

V6.3 remains the teacher and baseline. Its historical paired category delta
against the heuristic was +0.324444, 95% CI [0.281636, 0.367253], n=800;
against V6.2 +0.065, CI [0.02863, 0.10137]. Its top-four delta against the
heuristic was -0.005, CI [-0.03046, 0.02046]. This does not establish top-four
non-inferiority or an evolutionary ceiling.

The saved ensemble has seven members but only six distinct weight vectors.
`hall-g051-g49-13` and `hall-g050-g49-13` are identical. V7 merges their weights
by summation, preserving teacher votes. Deduplication is not itself a strength
improvement. Better archive selection, diversity, objectives and features could
still improve V6; the size of that opportunity is unknown.

V7 tests a different hypothesis: nonlinear, context-dependent player selection
and a learned estimate of the remaining draft are more useful than continuing
to optimize a fixed scoring family. More parameters are not proof of strength.

## Model and environment

- A permutation-equivariant player-set Transformer: width 96, four attention
  heads, two layers, 183,756 parameters. No player IDs or names as features.
- All players are tokens, with category Z values, raw stats, eligibility and
  ownership; global state includes draft progress and roster-slot counts.
- No ADP, ESPN draft rank or Player Rater input. This is a market-free research
  policy, not a promise of independence from the available player pool.
- Policy head scores every legal remaining player. Value head predicts eight
  category outcomes, normalized projected rank, top-four and top-one indicators.
- Exact repeated-slot matching covers PG/SG/SF/PF/C/G/F/UTIL/Bench. Both teacher
  and student use the same legality rules. Future availability is not guaranteed.
- Terminal targets use projected raw stats times GP with paired perturbations.
  No weekly schedule, waiver model, H2H season or playoffs are simulated.
- Opponents mix V6.3 and diverse market-free scoring anchors. Later training
  also samples historical neural checkpoints. This is not opponent-free learning
  and cannot cover every possible human strategy.

## Stages and stop rules

1. V7.0: teacher imitation plus terminal value training. 1,000 train and 120
   validation drafts, 14,560 own-pick states. Maximum 24 epochs, patience five.
2. Readiness: best validation-loss checkpoint must have at least 65% top-one
   teacher agreement. Otherwise stop before expensive arena evaluation. The
   subsequent category delta against V6.3 must be at least -0.15. These are
   engineering gates, not statistical claims of superiority.
3. V7.1: improve on counterfactual actions. Per iteration: 200 train and 40
   validation drafts, two searched decisions per draft, four candidates and
   three rollouts. That is 5,760 full continuations per iteration. Search produces
   soft policy targets; terminal played-draft outcomes supervise value. Replay
   mixes original imitation states with new states 50/50.
4. V7.2: a second improvement iteration, adding historical neural opponents.
   V7.1/V7.2 training currently uses full-rollout targets; learned-value short
   search is a separate evaluation ablation, not an unvalidated training oracle.
5. Freeze the iteration using validation category delta + 0.35 × top-four delta.
   Evaluate that checkpoint once on 240 new holdout scenarios. No selection by
   holdout results and no automatic production replacement.

## Fair evaluation

120 paired validation scenarios per iteration. Six arms: V6.3 and student
without search; each with equal-budget full-rollout search; each with equal-budget
short search using the same student value head. Full-search pairs use the same
V6.3 continuation policy. Short search stops at the next own turn and bootstraps
from value. Search occurs on only two own turns per draft, not all thirteen.

Each scenario has 48 full counterfactual continuations plus 48 short value-leaf
continuations and six completed outer drafts. Paired randomness and identical
opponents are shared across arms. Reports include category delta, rank gain and
top-four delta with 95% intervals. Opponent random weights differ across training,
validation and holdout, but some anchor families remain shared.

Fresh seeds are not a fresh NBA season: all use the same frozen 300-player input,
whose `stats_source` labels are currently `previous_season`. Generalization to
2027 projections, 14 teams and 11 categories is NOT established by this run.
Old V6.3 numbers must not be compared directly to V7 numbers: this arena and roster
legality differ. The new paired V6.3 measurements are the relevant baseline.

## Hardware, time and recovery

Six CPU workers generate/evaluate; training uses CUDA automatically when available.
Local preparation verified PyTorch 2.4.1+cu124 and GTX 1080 8 GB. A scratch
300-player, batch-24 forward/backward was finite, about 0.75 s on its first pass,
and allocated about 93 MB at peak. This is NOT an end-to-end training benchmark.
CPU draft rollouts can dominate even when the GPU is mostly idle.

Initial planning allowance: 4–12 hours for the first phase; 24–72 hours for the
whole research run, LOW confidence. These are provisional budgets, not a measured
ETA or a ten-hour deadline. Re-estimate from completed real episodes, evaluation
scenarios and epochs after authorization. A readiness failure stops earlier.

Each episode, epoch and evaluation scenario is saved atomically. Resume checks
code/config/input fingerprints and completed-stage checksums; changed inputs must
use a new output directory. An interrupted in-progress episode/scenario or epoch
is repeated; completed compatible work is retained. A Windows lock prevents two
runners writing the same run. Ctrl+C terminates the stage process tree. Force
closing/killing the parent may require checking for surviving child processes
before restarting. Logs provide 30-second heartbeats and completed-unit counts.

## Commands (do not execute training without user authorization)

Dry plan: `python scripts/draft_ml_v7_run.py`

Read-only hardware/input check: `python scripts/draft_ml_v7_run.py --preflight`

Training/resume after authorization, from a visible PowerShell console:
`powershell -NoExit -ExecutionPolicy Bypass -File scripts/run_draft_ml_v7.ps1 -Execute`

The same command resumes compatible progress. The console remains open after
completion, a gate stop or failure. Output: `artifacts/draft_ml/standard8-v7`.
Inspect `readiness-gate.json`, `frozen-selection.json`, `summary.json` and stage
logs. A process finishing successfully can mean a readiness stop, not a strong
trained model. Docker is not required for this standalone runner.

Dependencies: `requirements-v7.txt`. Tests cover eligibility, invariance,
deduplicated teacher votes, paired search, tiny training/checkpoint resume,
parallel generation and evaluation resume. Synthetic test training is not the
research launch.
