"""Illustrative 2026-27 ESPN league season scenarios; no roster mutations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import random
from pathlib import Path

from web.backend.dependencies import get_league_meta
from web.backend.services.matchup_engine import build_engine_inputs
from core.config import PERIODS
from core.matchup_mc import _simulate_team, aggregate_stats, stable_seed
from core.player_rates import build_player_rate
from core.projection import player_value
from core.season_mc import simulate_season
from core.simulation import compare_category_stats
from core.z_score import calculate_player_z_scores


TEAM_ID = 12
N_PAIR = int(os.getenv("FA_SIM_PAIR_TRIALS", "250"))
N_SEASON = int(os.getenv("FA_SIM_SEASON_TRIALS", "4000"))
CLAXTON_RETURN_WEEK = int(os.getenv("FA_SIM_CLAXTON_RETURN_WEEK", "3"))
SCENARIOS = ("base", "Collier", "Missi")
TARGET_NAMES = {"Collier": "Isaiah Collier", "Missi": "Yves Missi"}
OUTFILE = Path(__file__).with_name(
    "collier-vs-missi-2027-10-19.json" if CLAXTON_RETURN_WEEK == 3
    else "collier-vs-missi-2027-10-19-claxton-out.json"
)


def free_agent_row(meta, snapshot, player):
    stats = meta.get_player_stats(player, PERIODS["projected"], "avg")
    row = {
        "player_id": player.playerId,
        "name": player.name,
        "position": player.position,
        "eligible_slots": player.eligibleSlots,
        "schedule": player.schedule,
        "stats": stats,
        "z_scores": calculate_player_z_scores(stats, snapshot.league_metrics),
        "available": player.injuryStatus != "OUT",
        "injured": player.injured,
        "injury_status": player.injuryStatus,
        "lineup_slot": "BE",
    }
    rate = build_player_rate(row)
    row.update(rate=rate.as_dict(), stats=rate.mean, p_play=rate.p_play)
    return row


def adjusted_roster(players, week, scenario, additions):
    roster = [dict(player) for player in players]
    if week >= 2:
        for player in roster:
            if player["injury_status"] in ("DAY_TO_DAY", "DTD", "QUESTIONABLE"):
                player.update(p_play=1.0, available=True, injury_status="ACTIVE")
    if scenario != "base" and week >= CLAXTON_RETURN_WEEK:
        # Model a legal 13-player active roster after Claxton leaves IR.
        roster = [p for p in roster if p["name"] != "Collin Murray-Boyles"]
    if week >= CLAXTON_RETURN_WEEK:
        for player in roster:
            if player["name"] == "Nic Claxton":
                player.update(p_play=1.0, available=True, injured=False,
                              injury_status="ACTIVE", lineup_slot="BE")
    if scenario != "base":
        roster.append(additions[scenario])
    return roster


def sample_team(players, days, slots, team_id, week, scenario, count):
    output = []
    cache = {}
    for trial in range(count):
        rng = random.Random(stable_seed("collier-missi", team_id, week, scenario, trial))
        output.append(_simulate_team(players, days, slots, rng, cache))
    return output


def matchup_result(left, right, categories, reverse):
    results = [compare_category_stats(a, b, categories, reverse) for a, b in zip(left, right)]
    wins = sum(r["team1_wins"] > r["team2_wins"] for r in results)
    ties = sum(r["team1_wins"] == r["team2_wins"] for r in results)
    category_wins = {
        cat: sum(r["categories"][cat] == "win" for r in results) / len(results)
        for cat in categories
    }
    return {"p_win": wins / len(results), "p_tie": ties / len(results),
            "p_loss": 1 - (wins + ties) / len(results), "category_p_win": category_wins}


def total_stats(samples_by_week, categories):
    sums = defaultdict(float)
    count = 0
    for rows in samples_by_week:
        for row in rows:
            count += 1
            for key in ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD",
                        "FGM", "FGA", "FTM", "FTA", "3PA", "TO"):
                sums[key] += row.get(key, 0)
    # Mean weekly totals and season-weighted shooting ratios.
    return aggregate_stats({key: value / max(count / len(samples_by_week), 1)
                            for key, value in sums.items()})


def main():
    meta = get_league_meta()
    inputs = build_engine_inputs(meta, PERIODS["projected"])
    league = meta.league
    weeks = int(league.settings.reg_season_count)
    teams = meta.get_teams()
    team_names = {team.team_id: team.team_name for team in teams}
    available = {p.name: p for p in meta.get_free_agents(size=300)
                 if p.name in TARGET_NAMES.values()}
    if set(available) != set(TARGET_NAMES.values()):
        raise RuntimeError(f"Target free agents changed: {list(available)}")
    hydrated = league.player_info(playerId=[p.playerId for p in available.values()])
    if not isinstance(hydrated, list):
        hydrated = [hydrated]
    additions = {key: free_agent_row(meta, inputs["snapshot"], next(p for p in hydrated if p.name == name))
                 for key, name in TARGET_NAMES.items()}
    for key, row in additions.items():
        if not row["available"]:
            raise RuntimeError(f"{key} is unavailable")

    schedule = meta.get_schedule_matchups(1, weeks)
    games_by_week = defaultdict(list)
    for matchup in schedule:
        games_by_week[int(matchup["matchup_period"])].append(matchup)
    if any(len(games_by_week[w]) != len(teams) // 2 for w in range(1, weeks + 1)):
        raise RuntimeError("Incomplete fantasy matchup schedule")

    weekly_samples = {scenario: defaultdict(dict) for scenario in SCENARIOS}
    for week in range(1, weeks + 1):
        days = list(range(1 + 7 * (week - 1), 8 + 7 * (week - 1)))
        for team in teams:
            team_id = team.team_id
            base = adjusted_roster(inputs["players_by_team"][team_id], week, "base", additions)
            weekly_samples["base"][team_id][week] = sample_team(
                base, days, inputs["snapshot"].active_slots, team_id, week, "base", N_PAIR)
            if team_id == TEAM_ID:
                for scenario in SCENARIOS[1:]:
                    roster = adjusted_roster(inputs["players_by_team"][team_id], week, scenario, additions)
                    weekly_samples[scenario][team_id][week] = sample_team(
                        roster, days, inputs["snapshot"].active_slots, team_id, week, scenario, N_PAIR)
        if week % 4 == 0:
            print(f"Sampled {week}/{weeks} weeks", flush=True)

    base_teams = [{"team_id": t.team_id, "team_name": t.team_name, "wins": int(t.wins or 0),
                   "losses": int(t.losses or 0), "ties": int(t.ties or 0)} for t in teams]
    output = {
        "as_of": datetime.now(timezone.utc).isoformat(), "league_id": meta.league_id,
        "season": meta.year, "team_id": TEAM_ID, "regular_season_weeks": weeks,
        "matchup_trials": N_PAIR, "season_trials": N_SEASON,
        "claxton_return_week": CLAXTON_RETURN_WEEK,
        "assumptions": [
            "All non-target rosters and their present OUT/IR designations remain fixed.",
            "Current day-to-day players become available from week 2.",
            f"Nic Claxton returns in week {CLAXTON_RETURN_WEEK} in all three scenarios.",
            f"In add scenarios, Collin Murray-Boyles is removed from week {CLAXTON_RETURN_WEEK} to make legal room.",
            "Ben Simmons remains out for the full regular season.",
            "No subsequent transactions, trades, or changes in player roles are modeled.",
            "Daily NBA scoring periods grouped as seven days per fantasy week.",
        ],
        "scenarios": {},
    }
    all_stats = {team_id: total_stats([weekly_samples["base"][team_id][w] for w in range(1, weeks + 1)], inputs["categories"])
                 for team_id in team_names}
    for scenario in SCENARIOS:
        odds_rows = []
        user_weeks = []
        for week in range(1, weeks + 1):
            for matchup in games_by_week[week]:
                left, right = int(matchup["team1_id"]), int(matchup["team2_id"])
                left_rows = weekly_samples[scenario][TEAM_ID][week] if left == TEAM_ID and scenario != "base" else weekly_samples["base"][left][week]
                right_rows = weekly_samples[scenario][TEAM_ID][week] if right == TEAM_ID and scenario != "base" else weekly_samples["base"][right][week]
                result = matchup_result(left_rows, right_rows, inputs["categories"], inputs["reverse_categories"])
                odds_rows.append({"team1_id": left, "team2_id": right,
                                  "p_win": result["p_win"], "p_tie": result["p_tie"], "p_loss": result["p_loss"]})
                if TEAM_ID in (left, right):
                    user_weeks.append({"week": week, "opponent": team_names[right if left == TEAM_ID else left],
                                       "p_win": result["p_win"] if left == TEAM_ID else result["p_loss"],
                                       "category_p_win": result["category_p_win"] if left == TEAM_ID else {
                                           cat: 1 - result["category_p_win"][cat] for cat in inputs["categories"]}})
        strengths = defaultdict(list)
        for row in odds_rows:
            strengths[row["team1_id"]].append(row["p_win"] + row["p_tie"] / 2)
            strengths[row["team2_id"]].append(row["p_loss"] + row["p_tie"] / 2)
        mean_strengths = {team_id: sum(values) / len(values) for team_id, values in strengths.items()}
        season = simulate_season(base_teams, odds_rows, int(league.settings.playoff_team_count),
                                 trials=N_SEASON, seed=20271019, team_strengths=mean_strengths)
        standings = sorted(season, key=lambda row: row["expected_seed"])
        user = next(row for row in season if row["team_id"] == TEAM_ID)
        scenario_stats = dict(all_stats)
        if scenario != "base":
            scenario_stats[TEAM_ID] = total_stats([weekly_samples[scenario][TEAM_ID][w] for w in range(1, weeks + 1)], inputs["categories"])
        ranks = {cat: sorted(scenario_stats, key=lambda tid: scenario_stats[tid][cat], reverse=True).index(TEAM_ID) + 1
                 for cat in inputs["categories"]}
        output["scenarios"][scenario] = {
            "user": user,
            "standings": [{"team_id": row["team_id"], "team_name": row["team_name"],
                           "expected_seed": round(row["expected_seed"], 2),
                           "p_playoff": row["p_playoff"]} for row in standings],
            "category_ranks": ranks,
            "category_season_totals": {cat: round(scenario_stats[TEAM_ID][cat], 3) for cat in inputs["categories"]},
            "matchups": user_weeks,
        }
        print(scenario, "seed", round(user["expected_seed"], 2), "playoff", round(user["p_playoff"], 3), flush=True)
    OUTFILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote", OUTFILE, flush=True)


if __name__ == "__main__":
    main()
