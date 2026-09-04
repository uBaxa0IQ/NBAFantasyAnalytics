"""Чистая all-vs-all симуляция категорийных матчапов."""

from typing import Any, Dict, Iterable

from .config import CATEGORIES, REVERSE_CATEGORIES


def compare_category_stats(
    stats1: Dict[str, float],
    stats2: Dict[str, float],
    categories: Iterable[str] = CATEGORIES,
    reverse_categories=None,
) -> Dict[str, Any]:
    reverse = REVERSE_CATEGORIES if reverse_categories is None else set(reverse_categories)
    category_results = {}
    wins1 = 0
    wins2 = 0
    for category in categories:
        value1 = stats1.get(category, 0.0)
        value2 = stats2.get(category, 0.0)
        if category in reverse:
            value1, value2 = -value1, -value2
        if value1 > value2:
            category_results[category] = "win"
            wins1 += 1
        elif value2 > value1:
            category_results[category] = "loss"
            wins2 += 1
        else:
            category_results[category] = "tie"
    return {"team1_wins": wins1, "team2_wins": wins2, "categories": category_results}


def simulate_all_vs_all(
    teams: Dict[int, Dict[str, Any]],
    categories: Iterable[str] = CATEGORIES,
) -> list[Dict[str, Any]]:
    team_ids = list(teams)
    results = {
        team_id: {
            "team_id": team_id,
            "name": teams[team_id]["name"],
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "matchups": [],
        }
        for team_id in team_ids
    }

    for index, team1_id in enumerate(team_ids):
        for team2_id in team_ids[index + 1:]:
            stats1 = teams[team1_id]["stats"]
            stats2 = teams[team2_id]["stats"]
            comparison = compare_category_stats(stats1, stats2, categories)
            category_results = comparison["categories"]
            wins1 = comparison["team1_wins"]
            wins2 = comparison["team2_wins"]

            if wins1 > wins2:
                result1, result2 = "win", "loss"
                results[team1_id]["wins"] += 1
                results[team2_id]["losses"] += 1
            elif wins2 > wins1:
                result1, result2 = "loss", "win"
                results[team2_id]["wins"] += 1
                results[team1_id]["losses"] += 1
            else:
                result1 = result2 = "tie"
                results[team1_id]["ties"] += 1
                results[team2_id]["ties"] += 1

            results[team1_id]["matchups"].append(
                {
                    "opponent_id": team2_id,
                    "opponent_name": teams[team2_id]["name"],
                    "result": result1,
                    "score": f"{wins1}-{wins2}",
                    "categories": category_results,
                }
            )
            inverted = {
                category: "loss" if result == "win" else "win" if result == "loss" else "tie"
                for category, result in category_results.items()
            }
            results[team2_id]["matchups"].append(
                {
                    "opponent_id": team1_id,
                    "opponent_name": teams[team1_id]["name"],
                    "result": result2,
                    "score": f"{wins2}-{wins1}",
                    "categories": inverted,
                }
            )

    final_results = []
    for result in results.values():
        total = result["wins"] + result["losses"] + result["ties"]
        result["win_rate"] = round(
            ((result["wins"] + 0.5 * result["ties"]) / total * 100) if total else 0.0,
            1,
        )
        final_results.append(result)

    final_results.sort(key=lambda item: (item["win_rate"], item["wins"]), reverse=True)
    return final_results
