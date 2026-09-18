# V7.5 unknown-opponent search: test only

No training or promotion. Stop after 200 new full-draft scenarios (100 strong,
100 mixed), balanced across 10 seats. Same frozen 8-cat historical snapshot and
V6.3/V7 checkpoints. New v75:750909 namespace, disjoint from earlier experiments.

Five arms: V6.3, V7 without search, V7 with oracle late search, V7 with unknown-
opponent late search, and V7 with cheaper unknown-opponent search. Search at
own picks 10–13 only. Full budget up to 12 candidates x 8 rollouts; cheap budget
up to 6 x 3. Cheap candidate list starts with two V7 and two V6 proposals before
adding diverse candidates. This is a practical cheaper package, not an isolated
ablation of rollout count alone. Save realized counts and search durations.

Oracle receives the actual simulated opponent assignments. Blind search cannot:
it receives current observable draft state, an independent search seed and a
fixed prior mixture. Each rollout samples the strong/mixed policy families at
50/50, then assignments within that family. It receives neither the actual arena
label nor actual assignments. Prior is not fitted using final results. It does
not predict from opponents' earlier picks. Known families overlap the evaluation
population, so this is NOT evidence for arbitrary unseen human strategies.

Search branches use common V6.3 hero continuation. Actual policies replan at each
late pick. Actual-draft and terminal-audit random streams are separate from search.
Eight terminal perturbations averaged per draft are not independent sample units.

Primary: unknown vs V7, cheap vs V7 pooled equal arenas. 97.5% marginal normal
intervals for the two category contrasts (Bonferroni). Other contrasts and metrics
exploratory. Practical target +0.10 category; inspect rank/top4 before choosing
any next experiment. Fixed sample size, no quality-based early stopping. This
report does not trigger automatic training or deployment.

Runner: scripts/draft_v75_unknown_search.py (dry by default, --execute to run).
Visible launcher: scripts/run_draft_v75_unknown_search.ps1 -Execute.
Output: artifacts/draft_ml/standard8-v75-unknown-search. Atomic scenario saves,
fingerprint-checked resume, six CPU workers. Resilient writer retries temporary
Windows access errors; missed RUNNING heartbeat does not cancel computation.
Final output/data errors are not ignored. Viewer detached from work, completion
verified by matching current PID, provenance and complete summary.

Initial time allowance based on V7.4 measured run (~7.3 h active coordinator
time, with some discarded work around failure): 8–12 hours. Two expensive search
arms remain, plus one 18-vs-96 branch cheaper arm; prior-mixture rollouts may alter
cost. This is an estimate, to revise after completed scenarios, not a deadline.
