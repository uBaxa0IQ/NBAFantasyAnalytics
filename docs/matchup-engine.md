# Probabilistic Matchup Engine

The probabilistic engine is the third calculation mode. It does not replace the existing classic or calendar engines and can be selected independently in Settings.

## Scope

- ESPN scoring type: `H2H_MOST_CATEGORIES`.
- Dynamic league categories and lower-is-better categories such as turnovers.
- Current matchup, lineup decisions, regular-season playoff qualification, and a fixed seeded playoff bracket.
- Reproducible Monte Carlo results: every response includes the random seed, trial count, and engine version.

## Model

Player rates combine season, recent, and projected production with reliability shrinkage. Historical weekly variability is used when enough data exists; conservative category defaults are used otherwise. Percentages are simulated through makes and attempts, so team FG% and FT% remain attempt-weighted.

Availability is sampled once per player for the week from the current ESPN status. Expected return dates can make a player unavailable for only part of the scoring period. For every distinct availability scenario, the engine rebuilds a legal daily lineup and caches that decision.

The current score is treated as observed data. Only remaining scheduled games are simulated. Each trial compares every league category and determines the H2H most-categories result.

## API

`GET /api/matchup/odds`

Parameters:

- `team_id` — selected team.
- `week` — ESPN matchup period; defaults to the current period.
- `period` — statistical rate window (`total`, `last_15`, or another supported period).
- `remaining_only` — keep observed stats and simulate only unplayed dates.
- `trials` — requested simulation count, clamped to 100–5000.

The response includes `p_win`, `p_tie`, `p_loss`, per-category probabilities, expected stats, possible category-score distribution, flippable categories, Monte Carlo standard error, assumptions, and data-quality flags.

## Operational behavior

- Default interactive matchup forecast: 400 trials.
- Expensive league and bracket projections use smaller nested trial counts and short-lived caches.
- ESPN box-score responses and completed-week variability inputs are cached to avoid duplicate network work.
- Forecasts are recorded locally and resolved after a matchup finishes. The dashboard reports the Brier score and outcome accuracy when resolved forecasts exist.
- No automated roster transactions are performed. The engine provides decision support only.

## Known uncertainty

The engine cannot know late scratches, minutes restrictions, coaching decisions, or future roster moves. Those uncertainties are represented only through available status and statistical variance. Probabilities are estimates, not guarantees.
