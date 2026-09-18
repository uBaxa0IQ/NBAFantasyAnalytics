# V7.3 diagnostic only

No training, checkpoint writes, model selection or promotion. Stop after this
experiment and review with the user before choosing V6 or V7 development.

Runner: `scripts/draft_v73_diagnostic.py`; visible viewer/launcher:
`scripts/run_draft_v73_diagnostic.ps1 -Execute`. Default invocation is a dry plan.
The Python worker redirects output to files and does not depend on console writes.
Closing or selecting text in the viewer does not stop the worker. A file lock
prevents concurrent writers. Do not start a second worker to check progress.

## Experiment

Frozen standard8 snapshot, 10 teams, 13 slots, V6.3 ensemble and all three saved
V7 checkpoints. CPU inference, six workers; no GPU training required.

Three arenas, 30 drafts each, all 10 hero seats equally represented:

- Strong: V6.3 ensemble, its individual members, V7 iterations 0/1/2.
- Strategic: V6.3 plus category-biased punt/specialist synthetic anchors. These
  anchors are not certified optimal punt policies.
- Mixed: V6.3, frozen V7 policies and diverse anchors.

Each scenario compares complete V6.3 and V7.2 drafts, then samples own rounds
2, 7 and 12 on a shared prefix. Prefixes alternate V6.3 and V7 by draft index.
Both candidates and opponents must satisfy exact roster eligibility.

At each sampled state compare direct V6.3, direct V7, small V6.3-proposal search,
small V7-proposal search and expanded search. Small budgets are four candidates,
three rollouts. Expanded search covers up to twelve unique candidates, including
both small pools plus category-need and anchor-policy alternatives, eight rollouts.
Small budgets reuse the first three paired selection draws for fair noise control.

The selected actions are evaluated with EIGHT NEW rollout seeds, common across
actions. Selection samples are not used to report improvement. All continuations
use the same V6.3 hero policy. Opponent identities remain fixed to the arena draft;
their policy identities are known inside these branches. This deliberately tests
an optimistic search-capability condition, not real-world opponent prediction.

Reports separate all arenas and early/middle/late decisions. Aggregate local
confidence intervals use whole-draft averages, not correlated individual rollouts.
Full-draft baseline results are separate from local intervention benefits.
All comparisons are exploratory, unadjusted for multiple testing, and require a
new confirmation set before claiming strength. 30 drafts per arena may be too few
for small effects; inconclusive is a valid diagnostic result.

## Time, status and recovery

Six pilot jobs (two per arena) measure the actual cost; their files live under
`artifacts/draft_ml/standard8-v73-diagnostic/pilot`, separate from the main report.
Pilot and main use matching scenario seeds: pilot is a timing check, NOT an
independent evidence set and must not be added to main sample size.

Launch on 2026-09-08: pilot started first; the detached main worker uses
`--wait-pilot` and starts only after successful pilot completion. The visible
launcher uses `-Execute -WaitPilot`. Pilot failure/stale heartbeat prevents main
execution. The pilot is independent of the new network-training workflow.

A separate timing-only sample under pilot load measured full continuations at
early/middle/late positions (seconds): strong 9.91/6.27/0.91, strategic
13.09/8.28/1.20, mixed 6.81/4.14/0.69. Extrapolating maximum 136 continuations per
sampled state, 30 drafts per arena and six workers gives roughly 9.7 hours of
parallel branch work. This is not a measured full-run duration: candidate/action
deduplication reduces work, whereas different seats and opponent mixtures change
cost. Initial planning range is 8–12 hours including remaining preparation/pilot;
revise using actual completed-draft timings. Pilot has only two seats per arena.

Main status: `artifacts/draft_ml/standard8-v73-diagnostic/status.json`. Updated
at most roughly every 15 seconds while waiting for completed drafts. Fields:
phase, completed/total, elapsed_seconds, eta_seconds, updated_at, error, training.
Initial ETA is null until a full draft finishes; later estimates may vary by arena.
`COMPLETE_DIAGNOSTIC_ONLY` is successful completion. `FAILED` requires inspection.

Each entire diagnostic draft is atomic and resumable. Code/config/checkpoint
fingerprints reject incompatible reuse. An interrupted unfinished draft is redone.
The viewer's output/error logs are separate from durable per-draft results.
The viewer is not a stop button: terminating the worker requires terminating its
exact process tree, after verifying the target. No automatic training follows.

## Decision after completion

First check arena difficulty, noise and local benefit at larger search budgets.
If search produces independent gains, study whether a network can learn them.
If it does not, improve scoring/objectives/candidate coverage before training.
Do not interpret a failure of this bounded search as proof of a V6/V7 ceiling.
