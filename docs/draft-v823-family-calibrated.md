# V8.2.3 family-safe calibration

V8.2.3 freezes the three V8.2.2 checkpoints and treats its completed holdout as
development evidence for a new experiment. Only a category family with a
positive point estimate and a strictly positive confidence-interval lower bound
may enter calibration. Under that pre-registered rule, only 9-category leagues
are eligible; 8-, 10- and 11-category leagues deterministically abstain to the
balanced V8.1.1 policy.

Nine confidence policies are calibrated on 792 new 9-category paired drafts in
the `v823_calibration_validation` scenario namespace. A policy must provide at
least +0.003 normalized category value, avoid a lower interval below -0.003,
use at least three profiles, and keep its largest profile below 85%. Selection
uses the strongest confidence-interval lower bound.

Only successful calibration opens 212 new paired scenarios in
`v823_fresh_holdout`. The final system applies the selected policy to 9-category
leagues and no-punt V8.1.1 everywhere else. The format specifications have been
seen during prior research, but every stochastic draft/opponent scenario in
this run is new. Results remain research-only and are never auto-promoted.

Expected runtime is 0.5-1.4 hours. There is no training or label generation.
