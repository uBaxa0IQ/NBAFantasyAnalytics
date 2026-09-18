# V8.2.2 format-routed automatic strategy

V8.2.2 addresses the V8.2.1 validation collapse without opening its holdout or
weakening a gate after seeing results. V8.1.1 remains the frozen draft-policy
champion and the automatic strategy controller is still research-only.

The run reuses the 300 immutable V8.2 rollout-label shards. Training scenarios
are sampled by inverse square-root frequency of `(category count, oracle punt
profile)`, capped at 4x, so rare but rollout-supported profiles are learned
without allowing single examples to dominate.

The V3 scorer keeps category-specific punt binding and adds four format-routed
experts. Routing sees the active category set, team count, roster size and draft
state, but cannot see the candidate's punt mask or punt count. All profiles in a
draft state therefore use the same expert mixture. The loss combines listwise
ranking, utility-gap-weighted all-pairs ranking and normalized regression;
checkpoint selection also penalizes validation regret.

External validation uses the new `v822_validation_eval` scenario namespace.
This is required because V8.2.1 validation results informed the new design.
Passing requires positive pooled value, non-negative standard-8 value, no major
loss in another category family, at least five selected profiles and no profile
above 70%. The confidence policy is selected by the strongest lower confidence
bound, not the largest point estimate. Only a passing validation can open the
new `v822_holdout` namespace. Nothing is automatically promoted.

Estimated runtime is 1.7-3.8 hours: 0.6-1.5 hours training, 0.8-1.8 hours
validation, and 0.15-0.5 hours for holdout if the gate passes.
