# V8.2.1 category-bound automatic strategy

V8.2.1 reuses all 300 immutable V8.2 rollout-label states. It does not repeat
the expensive label generation. The failed additive scorer is replaced by a
category-bound network: each candidate keep/punt bit interacts with that specific
category's roster strength, availability and learned category embedding before
self-attention and pooling.

Training is listwise within each draft state. Utilities are normalized per state,
then optimized with distribution ranking, best-vs-rest margin and a small regression
term. This prevents tiny absolute utility differences from collapsing the learner
to one global profile.

Three independently initialized models form an ensemble. Nine confidence policies
combine vote requirements and margins over no-punt. Low-confidence decisions
explicitly abstain to a balanced strategy. Selection also rejects any controller
whose most common profile exceeds 70% or which uses fewer than five profiles.

Validation uses 2,376 fresh paired drafts with a new scenario seed. Only a passing
confidence policy opens a new 212-draft holdout. V8.1.1 remains frozen and nothing
is automatically promoted.

Estimated runtime: 1.5-3.5 hours, calibrated from a 9.28-second full-data epoch
and a 6.19-second paired evaluation draft. Fresh 2027 projections are still unavailable;
they require retraining this entire stack and creating another untouched holdout.
