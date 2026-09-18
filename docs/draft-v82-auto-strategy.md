# V8.2 automatic strategy discovery

V8.2 removes the requirement to choose a punt in advance. The V8.1.1 draft policy
is frozen. After three picks a rollout teacher compares strategy profiles using
the actual all-category terminal objective, so punted categories still count as
losses and over-punting is penalized by outcomes rather than a hand-written rule.

For 8-cat the complete 37-profile space (no punt, singles and pairs) is available.
For 10/11-cat the controller can enumerate up to 176/232 profiles including triples.
During label generation a deterministic state-aware screen sends 24 profiles to
paired continuation rollouts. A category-set network learns to rank those choices
without player ids, format ids, ADP or Player Rater. At inference it scores the
complete profile space and may select no punt.

The experiment uses 300 independent strategy states, at most 14,400 paired continuation
rollouts, 264 new validation drafts and a sealed 212-draft holdout. Validation must
beat balanced V8.1.1 before holdout opens. Nothing is promoted automatically.

The only available player snapshot still uses previous-season fallback. Fresh
2027 projected data requires full retraining and a new holdout.
