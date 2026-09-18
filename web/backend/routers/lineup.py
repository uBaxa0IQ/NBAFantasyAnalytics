"""Calendar-aware daily lineup optimization."""

from fastapi import APIRouter, Depends, HTTPException

from dependencies import get_league_meta
from core.config import DEFAULT_PERIOD
from services.projections import project_team_matchup
from services.legacy import rank_lineup_legacy
from services.matchup_engine import build_engine_inputs, find_opponent, optimize_lineup_by_win_probability, simulate_pair
from core.config import MATCHUP_MC_TRIALS


router = APIRouter(prefix="/api/lineup", tags=["lineup"])


@router.get("/{team_id}/optimize")
def optimize_team_lineup(
    team_id: int,
    period: str = DEFAULT_PERIOD,
    matchup_period: int | None = None,
    remaining_only: bool = True,
    punt_categories: str = "",
    calculation_engine: str = "calendar",
    league_meta=Depends(get_league_meta),
):
    """Return the best valid lineup for every remaining scoring day."""
    punts = tuple(
        category.strip()
        for category in punt_categories.split(",")
        if category.strip()
    )
    if calculation_engine == "legacy":
        try:
            return rank_lineup_legacy(league_meta, team_id, period, punts)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = project_team_matchup(
            league_meta,
            team_id=team_id,
            period=period,
            matchup_period=matchup_period,
            remaining_only=remaining_only,
            punt_categories=punts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    matchup = league_meta.get_matchup_box_score(result["matchup_period"], team_id)
    result["matchup_info"] = (
        {
            "opponent_name": matchup["opponent_name"],
            "opponent_id": matchup["opponent_id"],
            "week": result["matchup_period"],
        }
        if matchup
        else None
    )
    result["punt_categories"] = list(punts)
    result["method"] = "daily_slot_and_schedule_optimization"
    if calculation_engine == "probabilistic":
        if league_meta.scoring_type != "H2H_MOST_CATEGORIES":
            raise HTTPException(status_code=422, detail="Вероятностный движок поддерживает H2H Most Categories")
        opponent_id = find_opponent(league_meta, team_id, result["matchup_period"])
        if opponent_id is not None:
            inputs = build_engine_inputs(league_meta, period)
            players = inputs["players_by_team"].get(team_id, [])
            optimized = optimize_lineup_by_win_probability(
                league_meta, inputs, team_id, opponent_id, result["matchup_period"],
                remaining_only=remaining_only, trials=100,
            )
            result["selected_games"] = optimized["selected_games"]
            result["days"] = optimized["days"]
            baseline = simulate_pair(
                league_meta, inputs, team_id, opponent_id, result["matchup_period"],
                remaining_only=remaining_only, trials=MATCHUP_MC_TRIALS,
            )
            uncertain = [player for player in players if 0.0 < player.get("p_play", 1.0) < 1.0]
            scenarios = []
            for player in uncertain[:3]:
                identity = player.get("player_id") or player["name"]
                plays = simulate_pair(
                    league_meta, inputs, team_id, opponent_id, result["matchup_period"],
                    remaining_only=remaining_only, trials=100, seed=baseline["seed"],
                    availability_overrides1={identity: 1.0},
                )
                out = simulate_pair(
                    league_meta, inputs, team_id, opponent_id, result["matchup_period"],
                    remaining_only=remaining_only, trials=100, seed=baseline["seed"],
                    availability_overrides1={identity: 0.0},
                )
                scenarios.append({
                    "player_id": player.get("player_id"), "name": player["name"],
                    "status": player.get("injury_status"), "p_play": player["p_play"],
                    "if_plays_p_win": plays["p_win"], "if_out_p_win": out["p_win"],
                })
            result.update({
                "method": "probabilistic_delta_p_win",
                "note": "Каждая дневная замена оценена как точное изменение P(win) при легальном наборе стартеров; травмы, проценты и TO симулируются совместно.",
                "baseline_odds": optimized["baseline_odds"],
                "optimized_odds": optimized["optimized_odds"],
                "optimization_delta": optimized["delta"],
                "injury_scenarios": scenarios,
            })
    return result
