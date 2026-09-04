"""Full punt-strategy analysis for category fantasy leagues."""

from itertools import combinations
from statistics import median

from core.config import CATEGORIES
from core.snapshot import build_league_snapshot


MAX_AUTOMATIC_PUNTS = 4
MAX_ANALYZED_PUNTS = 5


def _category_result(team_value, opponent_value):
    if team_value > opponent_value:
        return "win"
    if team_value < opponent_value:
        return "loss"
    return "tie"


def _strategy_metrics(punts, category_profiles, opponent_results):
    punt_set = set(punts)
    retained = [category for category in CATEGORIES if category not in punt_set]
    core_control = sum(category_profiles[category]["win_rate"] for category in retained) / len(retained)

    matchup_wins = 0
    matchup_ties = 0
    expected_wins = 0.0
    for results in opponent_results.values():
        wins = sum(results[category] == "win" for category in retained)
        losses = len(punts) + sum(results[category] == "loss" for category in retained)
        ties = sum(results[category] == "tie" for category in retained)
        expected_wins += wins + ties * 0.5
        if wins > losses:
            matchup_wins += 1
        elif wins == losses:
            matchup_ties += 1

    opponent_count = max(len(opponent_results), 1)
    opponent_coverage = (matchup_wins + matchup_ties * 0.5) / opponent_count * 100
    margin = len(retained) - (len(CATEGORIES) // 2 + 1)
    locked = [category for category in retained if category_profiles[category]["win_rate"] >= 70]
    competitive = [category for category in retained if category_profiles[category]["win_rate"] >= 50]
    fragile = [category for category in retained if category_profiles[category]["win_rate"] < 40]
    score = 0.55 * opponent_coverage + 0.45 * core_control - len(punts) * 1.5

    if margin <= 1:
        risk = "высокий"
    elif len(punts) >= 2 or opponent_coverage < 60:
        risk = "средний"
    else:
        risk = "низкий"

    return {
        "punt_categories": list(punts),
        "punt_count": len(punts),
        "retained_categories": retained,
        "available_categories": len(retained),
        "core_control": round(core_control, 1),
        "opponent_coverage": round(opponent_coverage, 1),
        "expected_core_wins": round(expected_wins / opponent_count, 1),
        "margin_for_error": margin,
        "locked_categories": locked,
        "competitive_categories": competitive,
        "fragile_categories": fragile,
        "risk": risk,
        "strategy_score": round(score, 2),
    }


def analyze_punt_strategies(team_scores, team_id, roster):
    """Evaluate every viable punt combination for an unchanged roster."""
    team_id = int(team_id)
    if team_id not in team_scores or len(team_scores) < 2:
        raise ValueError("Not enough teams to analyze punt strategies")

    opponents = {key: value for key, value in team_scores.items() if int(key) != team_id}
    category_profiles = {}
    opponent_results = {}
    roster_size = max(len(roster), 1)

    for opponent_id, scores in opponents.items():
        opponent_results[opponent_id] = {
            category: _category_result(
                team_scores[team_id].get(category, 0.0),
                scores.get(category, 0.0),
            )
            for category in CATEGORIES
        }

    for category in CATEGORIES:
        team_value = team_scores[team_id].get(category, 0.0)
        league_values = [scores.get(category, 0.0) for scores in team_scores.values()]
        wins = sum(result[category] == "win" for result in opponent_results.values())
        ties = sum(result[category] == "tie" for result in opponent_results.values())
        win_rate = (wins + ties * 0.5) / len(opponents) * 100
        rank = 1 + sum(value > team_value for value in league_values)
        negative_players = sum(
            (player.get("z_scores") or {}).get(category, 0.0) < 0
            for player in roster
        )
        category_profiles[category] = {
            "category": category,
            "rank": rank,
            "total_teams": len(team_scores),
            "win_rate": round(win_rate, 1),
            "distance_to_median": round(median(league_values) - team_value, 2),
            "negative_players": negative_players,
            "roster_size": len(roster),
            "distributed_weakness": round(negative_players / roster_size * 100, 1),
        }

    strategies_by_depth = []
    all_best = []
    strategy_options = []
    baseline = None
    max_punts = min(MAX_ANALYZED_PUNTS, len(CATEGORIES) - (len(CATEGORIES) // 2 + 1))
    for punt_count in range(max_punts + 1):
        strategies = [
            _strategy_metrics(punts, category_profiles, opponent_results)
            for punts in combinations(CATEGORIES, punt_count)
        ]
        strategies.sort(
            key=lambda item: (
                item["strategy_score"],
                item["opponent_coverage"],
                item["core_control"],
            ),
            reverse=True,
        )
        best = strategies[0]
        if baseline is None:
            baseline = best
        for strategy in strategies:
            strategy["control_gain"] = round(strategy["core_control"] - baseline["core_control"], 1)
            strategy["coverage_delta"] = round(strategy["opponent_coverage"] - baseline["opponent_coverage"], 1)
            strategy_options.append({
                key: strategy[key]
                for key in (
                    "punt_categories",
                    "punt_count",
                    "available_categories",
                    "core_control",
                    "opponent_coverage",
                    "expected_core_wins",
                    "margin_for_error",
                    "risk",
                    "strategy_score",
                    "control_gain",
                    "coverage_delta",
                )
            })
        alternatives = []
        for strategy in strategies[1:4]:
            alternative = dict(strategy)
            alternatives.append(alternative)
        strategies_by_depth.append({
            "punt_count": punt_count,
            "best": best,
            "alternatives": alternatives,
        })
        all_best.append(best)

    minimum_coverage = max(50.0, baseline["opponent_coverage"] - 10.0)
    eligible = [
        strategy
        for strategy in all_best
        if strategy["punt_count"] <= min(MAX_AUTOMATIC_PUNTS, max(0, max_punts - 1))
        and strategy["opponent_coverage"] >= minimum_coverage
    ]
    recommendation = max(eligible or [baseline], key=lambda item: item["strategy_score"])

    return {
        "baseline": baseline,
        "max_punts": max_punts,
        "winning_categories": len(CATEGORIES) // 2 + 1,
        "recommendation": recommendation,
        "strategies_by_depth": strategies_by_depth,
        "strategy_options": strategy_options,
        "category_profiles": [category_profiles[category] for category in CATEGORIES],
        "total_combinations": sum(
            len(list(combinations(CATEGORIES, count)))
            for count in range(max_punts + 1)
        ),
    }


def recommend_punt_strategies(league_metadata, team_id: int, period: str):
    snapshot = build_league_snapshot(league_metadata, period)
    roster = [player.as_projection_player() for player in snapshot.team_players(team_id)]
    if not roster:
        raise ValueError("Team not found or roster is empty")

    team_scores = {}
    for team in league_metadata.league.teams:
        current_team_id = int(team.team_id)
        players = [
            player.as_projection_player()
            for player in snapshot.team_players(current_team_id)
        ]
        if players:
            team_scores[current_team_id] = {
                category: sum(
                    (player.get("z_scores") or {}).get(category, 0.0)
                    for player in players
                )
                for category in CATEGORIES
            }

    result = analyze_punt_strategies(team_scores, team_id, roster)
    result.update({
        "team_id": int(team_id),
        "period": period,
        "method": "exhaustive_punt_combination_analysis",
        "disclaimer": "Стратегии оценивают ядро текущего состава; сам выбор punt не меняет статистику игроков.",
    })
    return result
