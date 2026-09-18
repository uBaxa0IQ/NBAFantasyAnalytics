# V8.2.4 rollout-label reliability audit

V8.2.4 is a measurement experiment, not a new model. It freezes V8.1.1 and
does not use V8.2.x validation or holdout outcomes as targets. The purpose is to
measure whether automatic-punt labels are reproducible before spending more
compute on architecture or training.

The audit covers 16 formats: four team/roster variants for each of 8, 9, 10 and
11 categories. Four spread draft seats per format create 64 states. At round
three, the existing deterministic shortlist supplies 24 candidate strategies.
Every candidate receives eight paired rollouts and four terminal uncertainty
draws. Random scenario keys are shared across profiles, and all 49,152 terminal
outcomes are retained rather than reduced to one mean.

Each profile is an independent atomic shard, so interruption loses at most one
profile's eight continuations. Analysis splits rollouts 4+4 and measures rank
correlation, top-three overlap, cross-half regret, cross-half positive gain,
profile sign agreement and whether best-vs-no-punt is statistically resolved.

The pre-registered readiness gate requires median Spearman correlation >= 0.6,
top-three overlap of at least two profiles in >= 60% of states, positive
cross-half selected gain in >= 80% of decisions, and mean cross-half regret <=
0.005. Passing recommends an adaptive distributional dataset. Failure recommends
increasing label precision before any further model training.

Expected runtime is 5-12 hours on six CPU workers. Analysis takes minutes. No
checkpoint is promoted and no training occurs.
