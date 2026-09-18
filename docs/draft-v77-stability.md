# V7.7 stability gate before universal architecture

Scope: two additional V7.6 optimization seeds (770912, 770913) on the exact same
verified frozen 400/80 draft dataset and original V7 warm start. Same architecture,
hyperparameters and validation-loss checkpoint rule. This checks optimizer/shuffle
sensitivity, NOT sensitivity to generating a whole new training corpus.

Evaluate every version, not a selected lucky seed: old V7, frozen V7.6, repeat1,
repeat2. 400 fresh full-draft scenarios, 100 per condition, all 10 seats balanced.
No search and no production promotion. Opponents do not receive replica policies.

Conditions: familiar strong, familiar mixed, unseen synthetic rules, input shift.
New rules alternate random top-five V6 choices and a nonlinear weak-category
roster-need score. This is not coverage of all human or adversarial strategies.
Input shift perturbs per-player GP (~12%) and raw stats (~8%), enforces shooting
component bounds, recomputes percentage inputs and Z scores over the player pool.
It therefore tests a perturbed-and-renormalized input pipeline, not a new season
or a clean isolation of individual feature sensitivity. Outcome perturbations
use separate seeds and are averaged over eight draws per complete draft.

All three version-vs-old category contrasts use 98.333% marginal intervals
(Bonferroni across three predeclared pooled comparisons). Condition-level and
other metrics exploratory. Every seed stays in report; no automatic champion
selection, no automatic universal architecture training. Review small losses and
per-condition regressions as well as pooled gain. Novel scenarios are independent
of the earlier holdouts, but retain one historical player dataset.

Existing V7.6 artifact checksums are verified. The audited compatibility wrapper
keeps unrelated matchup/season edits outside the old experiment identity and
prohibits importing those modules into experiment execution. Resumption requires
matching new-run provenance and completed-stage checksums. GPU fits run sequentially;
evaluation uses six CPU workers. JSON heartbeat/write protections are retained.

Runner: scripts/draft_v77_stability.py (--execute required).
Viewer: scripts/run_draft_v77_stability.ps1 -Execute.
Output: artifacts/draft_ml/standard8-v77-stability.
Expected time 2–4 hours: roughly 20–60 minutes for two fits and 1–3 hours for
1600 full model-draft trajectories, plus input perturbation/normalization and
eight terminal draws. Based on earlier timings, not a measured completion promise.

After the report: decide whether to freeze V7.6 as a trustworthy reference and
proceed to architecture conditioned on league categories, size and roster slots.
This script itself still supports ONLY 8 categories and 10 teams.
