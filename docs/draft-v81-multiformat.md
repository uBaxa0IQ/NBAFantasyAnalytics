# V8.1 multi-format curriculum

V8.1 is the first actual training of the universal V8 architecture. It starts from
the exact V7.6-to-V8.0 migration and never uses player identity, ESPN ADP or Player
Rater as an own-policy input.

Twelve training formats cross standard 8-cat, standard 9-cat with reverse TO and
the custom 11-cat format with 8/10/12/14 teams and 11/13/15-player roster layouts.
Every draft seat is balanced inside every format. The same historical 300-player
raw-stat snapshot is re-normalized separately for each category set.

Explicit strategy inputs cover no punt and one/two/three-category punts. Search
targets are generated at four early/middle/late decisions using eight candidates,
three blind rollouts and an independent two-rollout acceptance audit. Opponents are
sampled from six market-free synthetic families. Training batches weight formats
equally instead of allowing 14-team formats to dominate.

The validation gate requires standard8 no-punt normalized category delta against
V8.0 of at least -0.02 and non-reference delta against the universal adaptive
heuristic of at least -0.05. Only then is the checkpoint frozen and the holdout
opened. Holdout configurations include 9/11/13-team interpolation, new roster
combinations and a ten-category subset absent from training. Two primary contrasts
use Bonferroni-adjusted intervals. No automatic promotion occurs.

The run generates 1,320 data drafts with 5,280 searched decisions, 126,720
selection continuations and at most 21,120 independent audit continuations, then
evaluates 740 paired drafts. A local one-worker benchmark measured 175.3 seconds
for one representative generation episode and 7.1 seconds for one evaluation
episode. With six workers, the conservative expected runtime is 14-21 hours,
dominated by early/mid-draft CPU continuation simulation. GPU is used for model
fitting. Completed episodes, epochs and evaluation scenarios resume.

Dry/preflight: `python scripts/draft_v81_multiformat.py`

Authorized launch: `powershell -NoExit -ExecutionPolicy Bypass -File scripts/run_draft_v81_multiformat.ps1 -Execute`
