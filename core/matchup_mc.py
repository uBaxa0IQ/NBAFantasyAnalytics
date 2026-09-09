"""Seeded Monte Carlo engine for H2H most-categories basketball matchups."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import hashlib
import math
import random
from typing import Any, Iterable, Mapping, Sequence

from .projection import DEFAULT_LINEUP_SLOTS, optimize_daily_lineup
from .simulation import compare_category_stats


ENGINE_VERSION = "matchup-mc-v1"
COMPONENTS = ("PTS", "REB", "AST", "STL", "BLK", "DD", "TO", "FGM", "FGA", "FTM", "FTA", "3PM", "3PA")


def stable_seed(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def aggregate_stats(*rows: Mapping[str, float]) -> dict[str, float]:
    totals = {key: 0.0 for key in COMPONENTS}
    for row in rows:
        for key in COMPONENTS:
            value = row.get(key, 0.0)
            if isinstance(value, (int, float)):
                totals[key] += float(value)
    totals["FG%"] = totals["FGM"] / totals["FGA"] if totals["FGA"] else 0.0
    totals["FT%"] = totals["FTM"] / totals["FTA"] if totals["FTA"] else 0.0
    totals["3PT%"] = totals["3PM"] / totals["3PA"] if totals["3PA"] else 0.0
    totals["A/TO"] = totals["AST"] / totals["TO"] if totals["TO"] else totals["AST"]
    return totals


def _binomial(rng: random.Random, attempts: int, probability: float) -> int:
    probability = min(1.0, max(0.0, probability))
    return sum(rng.random() < probability for _ in range(max(0, attempts)))


def _sample_game(player: Mapping[str, Any], rng: random.Random) -> dict[str, float]:
    rate = player.get("rate") or {}
    mean = rate.get("mean") or player.get("stats") or {}
    std = rate.get("std") or {}
    latent = rng.gauss(0.0, 1.0)

    def count(key: str, integer: bool = True) -> float:
        mu = max(0.0, float(mean.get(key, 0.0) or 0.0))
        sigma = max(0.12, float(std.get(key, max(0.2, mu * 0.5)) or 0.0))
        z = 0.42 * latent + math.sqrt(1 - 0.42**2) * rng.gauss(0.0, 1.0)
        value = max(0.0, mu + sigma * z)
        return float(round(value)) if integer else value

    fga = int(count("FGA"))
    fta = int(count("FTA"))
    tpa = int(count("3PA"))
    fg_pct = float(mean.get("FGM", 0.0) or 0.0) / max(float(mean.get("FGA", 0.0) or 0.0), 1e-9)
    ft_pct = float(mean.get("FTM", 0.0) or 0.0) / max(float(mean.get("FTA", 0.0) or 0.0), 1e-9)
    tp_pct = float(mean.get("3PM", 0.0) or 0.0) / max(float(mean.get("3PA", 0.0) or 0.0), 1e-9)
    result = {key: count(key) for key in ("PTS", "REB", "AST", "STL", "BLK", "TO")}
    result.update({
        "FGA": float(fga), "FGM": float(_binomial(rng, fga, fg_pct)),
        "FTA": float(fta), "FTM": float(_binomial(rng, fta, ft_pct)),
        "3PA": float(tpa), "3PM": float(_binomial(rng, tpa, tp_pct)),
        "DD": float(rng.random() < min(1.0, max(0.0, float(mean.get("DD", 0.0) or 0.0)))),
    })
    return result


def _has_game(player: Mapping[str, Any], scoring_period: int) -> bool:
    schedule = player.get("schedule") or {}
    game = schedule.get(str(scoring_period), schedule.get(scoring_period))
    if game is None:
        return False
    if player.get("future_only"):
        game_date = (game or {}).get("date")
        if isinstance(game_date, datetime) and game_date <= datetime.now(game_date.tzinfo):
            return False
    return True


def _simulate_team(
    players: Sequence[Mapping[str, Any]],
    scoring_periods: Sequence[int],
    slots: Sequence[str],
    rng: random.Random,
    lineup_cache: dict[tuple[Any, ...], list[Mapping[str, Any]]],
    availability_overrides: Mapping[Any, float] | None = None,
) -> dict[str, float]:
    overrides = availability_overrides or {}
    week_available: dict[Any, bool] = {}
    for player in players:
        identity = player.get("player_id") or player.get("name")
        p_play = float(overrides.get(identity, player.get("p_play", (player.get("rate") or {}).get("p_play", 1.0))))
        week_available[identity] = rng.random() < min(1.0, max(0.0, p_play))

    games = []
    for scoring_period in scoring_periods:
        available = []
        for player in players:
            if not _has_game(player, scoring_period):
                continue
            identity = player.get("player_id") or player.get("name")
            is_available = week_available[identity]
            if not is_available and str(player.get("lineup_slot") or "").upper() != "IR":
                return_date = player.get("expected_return_date")
                if isinstance(return_date, str):
                    try:
                        return_date = date.fromisoformat(return_date[:10])
                    except ValueError:
                        return_date = None
                if isinstance(return_date, datetime):
                    return_date = return_date.date()
                game = (player.get("schedule") or {}).get(str(scoring_period), (player.get("schedule") or {}).get(scoring_period)) or {}
                game_date = game.get("date")
                if isinstance(game_date, datetime) and isinstance(return_date, date):
                    is_available = game_date.date() >= return_date
            if is_available:
                available.append(player)
        mask = tuple(sorted(str(p.get("player_id") or p.get("name")) for p in available))
        key = (scoring_period, mask)
        starters = lineup_cache.get(key)
        if starters is None:
            lineup_players = [{**p, "available": True} for p in available]
            optimized = optimize_daily_lineup(lineup_players, slots=slots, fill_slots=True)
            starters = [item["player"] for item in optimized["starters"]]
            lineup_cache[key] = starters
        games.extend(_sample_game(player, rng) for player in starters)
    return aggregate_stats(*games)


def simulate_matchup_odds(
    players1: Sequence[Mapping[str, Any]],
    players2: Sequence[Mapping[str, Any]],
    scoring_periods: Sequence[int],
    *,
    actual1: Mapping[str, float] | None = None,
    actual2: Mapping[str, float] | None = None,
    categories: Iterable[str],
    reverse_categories: Iterable[str] = (),
    slots: Sequence[str] = DEFAULT_LINEUP_SLOTS,
    trials: int = 600,
    seed: int | None = None,
    team1_id: int | None = None,
    team2_id: int | None = None,
    availability_overrides1: Mapping[Any, float] | None = None,
    availability_overrides2: Mapping[Any, float] | None = None,
) -> dict[str, Any]:
    trials = max(100, min(int(trials), 5000))
    categories = tuple(categories)
    reverse_categories = tuple(reverse_categories)
    seed = int(seed if seed is not None else stable_seed(team1_id, team2_id, scoring_periods, trials, ENGINE_VERSION))
    rng = random.Random(seed)
    outcomes = Counter()
    scores = Counter()
    category_outcomes = {cat: Counter() for cat in categories}
    margins = {cat: [] for cat in categories}
    stat_sums1 = {key: 0.0 for key in COMPONENTS}
    stat_sums2 = {key: 0.0 for key in COMPONENTS}
    cache1: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    cache2: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}

    for _ in range(trials):
        future1 = _simulate_team(players1, scoring_periods, slots, rng, cache1, availability_overrides1)
        future2 = _simulate_team(players2, scoring_periods, slots, rng, cache2, availability_overrides2)
        stats1 = aggregate_stats(actual1 or {}, future1)
        stats2 = aggregate_stats(actual2 or {}, future2)
        result = compare_category_stats(stats1, stats2, categories, reverse_categories)
        for key in COMPONENTS:
            stat_sums1[key] += stats1.get(key, 0.0)
            stat_sums2[key] += stats2.get(key, 0.0)
        wins1, wins2 = result["team1_wins"], result["team2_wins"]
        ties = len(categories) - wins1 - wins2
        outcome = "win" if wins1 > wins2 else "loss" if wins2 > wins1 else "tie"
        outcomes[outcome] += 1
        scores[f"{wins1}-{wins2}-{ties}"] += 1
        for cat, cat_outcome in result["categories"].items():
            category_outcomes[cat][cat_outcome] += 1
            direction = -1.0 if cat in reverse_categories else 1.0
            margins[cat].append(direction * (stats1.get(cat, 0.0) - stats2.get(cat, 0.0)))

    category_result = {}
    for cat in categories:
        values = sorted(margins[cat])
        category_result[cat] = {
            "p_win": category_outcomes[cat]["win"] / trials,
            "p_tie": category_outcomes[cat]["tie"] / trials,
            "p_loss": category_outcomes[cat]["loss"] / trials,
            "mean_margin": sum(values) / trials,
            "q10_margin": values[int(0.10 * (trials - 1))],
            "q90_margin": values[int(0.90 * (trials - 1))],
        }
    p_win = outcomes["win"] / trials
    expected1 = aggregate_stats({key: value / trials for key, value in stat_sums1.items()})
    expected2 = aggregate_stats({key: value / trials for key, value in stat_sums2.items()})
    scheduled_games1 = sum(_has_game(player, day) for player in players1 for day in scoring_periods)
    scheduled_games2 = sum(_has_game(player, day) for player in players2 for day in scoring_periods)
    return {
        "team1_id": team1_id, "team2_id": team2_id,
        "p_win": p_win, "p_tie": outcomes["tie"] / trials, "p_loss": outcomes["loss"] / trials,
        "categories": category_result,
        "expected_stats": [expected1, expected2],
        "score_distribution": dict(sorted(((score, count / trials) for score, count in scores.items()), key=lambda x: x[1], reverse=True)),
        "flippable": [cat for cat, value in category_result.items() if 0.25 <= value["p_win"] <= 0.75],
        "method": "probabilistic_calendar_mc", "engine_version": ENGINE_VERSION,
        "trials": trials, "seed": seed,
        "monte_carlo_se": math.sqrt(max(p_win * (1 - p_win), 0.0) / trials),
        "assumptions": [
            "H2H most categories", "current rosters remain unchanged",
            "injury statuses use weekly availability scenarios", "lineups are re-optimized for sampled availability",
        ],
        "quality_flags": (["team1_has_no_scheduled_games"] if not scheduled_games1 else []) + (["team2_has_no_scheduled_games"] if not scheduled_games2 else []),
    }
