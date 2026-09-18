# V8.0 universal architecture migration

V8.0 is an architecture/parity gate, not a new strength claim. It decomposes the
fixed V7.6 player projection into raw-stat/eligibility features plus dynamically
selected category embeddings. Its value output is queried by category ID. League
size and roster length are explicit inputs; relative-seat role embeddings support
up to 16 teams. Per-player drafted-pick and draft-age features preserve the observed
pick sequence. The prepared research scope is 8-14 teams.

Supported category vocabulary: FG%, FT%, 3PM, 3PT% (alias 3P%), REB, AST, A/TO,
STL, BLK, DD, PTS and TO. Category weights allow no-punt or explicit-punt inputs.
Roster slot counts and arbitrary repeated PG/SG/SF/PF/C/G/F/UTIL/Bench slots are
encoded. Terminal evaluation accepts an explicit reverse-category set.

V7.6 policy/value weights are migrated exactly for standard8. Added raw TO/DD,
league dimensions and category-context parameters begin neutral. Twenty complete
drafts compare logits, values and actions at every own decision. Then 200 paired
full drafts cover strong, mixed, unseen-rule and projection-shift conditions. Any
numerical/action/outcome disagreement fails the gate. There is no V8 training and
no production promotion in this run.

Dry/preflight: `python scripts/draft_v80_universal.py`

Authorized run: `powershell -NoExit -ExecutionPolicy Bypass -File scripts/run_draft_v80_universal.ps1 -Execute`

Expected time: 0.3-1.0 hour. After a pass, V8.1 will generate and train a true
multi-format corpus over different categories, team counts and roster settings.
