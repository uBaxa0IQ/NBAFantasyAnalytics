# V8.1.1 frozen-base residual recovery

V8.1.1 addresses the V8.1 validation regression without regenerating self-play data.
The exact V8.0/V7.6 policy is embedded as a frozen teacher. A small residual adapter
sees raw player features, category descriptors and weights, team count, roster size
and roster ownership. It never receives player identity, format identity, ESPN ADP
or Player Rater.

Only independently audited V8.1 search improvements supervise policy changes.
All states also receive policy distillation from V8.0 plus a trust-region penalty.
Rejected searches and ordinary draft states therefore preserve the strong source
policy instead of imitating the weaker heuristic targets that caused V8.1 forgetting.
Value learning has reduced weight and cannot modify the frozen base.

Three adapter seeds are trained from the same 1,320 immutable V8.1 shards. Five
adapter strengths per seed are compared on the already-open 528-draft validation
set using paired scenarios. A candidate must retain standard 8-cat, improve over
V8.0 on non-reference formats, and remain above the adaptive heuristic. If none
passes, the run stops and V8.0 remains the winner. Only one selected checkpoint may
open the 212-draft frozen holdout. No model is automatically promoted.

Expected runtime is 2-4.5 hours: roughly 0.5-1.5 hours for three GPU fits, 1-2.5
hours for the CPU validation sweep, and 0.15-0.5 hours for holdout. All seeds,
epochs, candidates and scenarios resume.

Dry/preflight: `python scripts/draft_v811_residual.py`

Authorized launch: `powershell -NoExit -ExecutionPolicy Bypass -File scripts/run_draft_v811_residual.ps1 -Execute`
