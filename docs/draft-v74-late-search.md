# V7.4: fixed late-search full-draft experiment

Research only. No training, production integration, automatic candidate selection
or promotion. Stop for user review after completion.

## Frozen design

100 scenarios each on strong and mixed V7.3 arenas; 200 independent drafts,
balanced across 10 hero seats. New seed namespace `v74:740909`. Old V7.3 results
motivated the hypothesis; those scenarios are not reused as confirmation data.

Four paired full-draft arms: V6.3, V7 iteration 2, V6.3 plus late search, V7 plus
late search. Search is applied at each of own picks 10, 11, 12, 13. The policy
replans after each actual selection. All arms share actual opponent randomness.

Search: up to 12 unique legal candidates from both baseline rankings, category
needs and anchor alternatives; 8 continuations each. Every branch uses V6.3 as
the remaining hero policy, with no nested search. Both search arms have identical
budgets and continuation evaluator. Candidate deduplication and legal-pool size
may reduce realized counts; counts and elapsed search time are saved per arm.

Selection seeds are disjoint from actual-draft and terminal-audit seeds. Eight
terminal perturbations are averaged per draft. These are NOT eight independent
drafts. Complete draft is the unit for confidence intervals and comparisons.

Primary endpoints: pooled equal-arena category delta of V6.3+search vs V6.3 and
V7+search vs V7. Marginal 97.5% normal intervals use Bonferroni for those two
category contrasts. Other metrics and per-arena 95% intervals are exploratory.
Predeclared practical target +0.10 category; review rank deterioration against
0.10 place and top-four deterioration against 2 percentage points. These are
review criteria, not automatic promotion rules. Keep the fixed 200-scenario
sample size; no stopping based on interim quality and no tuning on these results.

The arena policies are fixed and known inside search: an optimistic search-
capability test, not proof of performance against unknown humans. This is one
historical 8-category, 10-team player snapshot, not a weekly H2H season.

## Launch and recovery

Dry plan: `python scripts/draft_v74_late_search.py`.

Visible launcher: `scripts/run_draft_v74_late_search.ps1 -Execute`.
Worker is detached from console output. Viewer selection or closure does not
stop computation. The viewer retains the process handle and checks current-worker
status plus matching summary before declaring success. An unavailable exit code
is not treated as a failure. Logs are timestamped; saved old logs are preserved.

Output: `artifacts/draft_ml/standard8-v74-late-search`. `status.json` has current
PID, heartbeat, completed count, ETA and explicit phase. `plan.json` freezes the
design; `episodes/` contains atomic complete scenarios; `summary.json` contains
the final report. Resume skips compatible completed scenarios, repeats incomplete
ones and rejects code/config/checkpoint fingerprint mismatches. Do not start a
second worker; a Windows file lock protects the output directory.

No further experiment is started automatically after this one.

Preparation on 2026-09-09: full suite 154 tests passed. Timing-only samples for
one seat per arena measured remaining-draft continuations at picks 10–13:
strong 1.734/1.594/0.610/0.609 seconds; mixed 1.843/1.656/0.579/0.515 seconds.
Extrapolating maximum 96 branches per searched pick, two search arms, 100
scenarios per arena and six workers yields 8.12 hours. Initial planning range
8–12 hours; revise from real completed-scenario throughput. This microbenchmark
is not an end-to-end run or a guarantee under parallel CPU contention.
