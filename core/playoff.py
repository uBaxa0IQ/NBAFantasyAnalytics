"""Чистые функции для определения состояния и посева плей-офф ESPN."""

import math
from typing import Any, Dict, Iterable, List, Optional


def get_playoff_periods(settings) -> List[int]:
    """Возвращает matchup periods плей-офф из настроек лиги."""
    regular_season_periods = int(getattr(settings, "reg_season_count", 0) or 0)
    matchup_periods = getattr(settings, "matchup_periods", {}) or {}
    return sorted(
        int(period)
        for period in matchup_periods
        if int(period) > regular_season_periods
    )


def get_playoff_context(league) -> Dict[str, Any]:
    """Формирует состояние сезона исключительно из ESPN league settings."""
    current_period = int(league.currentMatchupPeriod)
    settings = league.settings
    playoff_periods = get_playoff_periods(settings)
    playoff_start = playoff_periods[0] if playoff_periods else None
    is_playoff_period = current_period in playoff_periods
    scoring_period = int(getattr(league, "scoringPeriodId", 0) or 0)
    final_scoring_period = int(getattr(league, "finalScoringPeriod", 0) or 0)
    season_complete = final_scoring_period > 0 and scoring_period > final_scoring_period
    is_playoff = is_playoff_period and not season_complete
    round_number = playoff_periods.index(current_period) + 1 if is_playoff_period else None
    playoff_team_count = int(getattr(settings, "playoff_team_count", 0) or 0)

    return {
        "current_week": current_period,
        "regular_season_periods": int(getattr(settings, "reg_season_count", 0) or 0),
        "playoff_start_week": playoff_start,
        "playoff_periods": playoff_periods,
        "playoff_team_count": playoff_team_count,
        "playoff_seed_tie_rule": getattr(settings, "playoff_seed_tie_rule", None),
        "is_playoff": is_playoff,
        "is_playoff_period": is_playoff_period,
        "season_complete": season_complete,
        "phase": "complete" if season_complete else ("playoffs" if is_playoff else "regular"),
        "round": round_number,
        "round_name": get_round_name(round_number, playoff_team_count),
    }


def get_round_name(round_number: Optional[int], playoff_team_count: int) -> Optional[str]:
    if round_number is None or playoff_team_count <= 1:
        return None

    total_rounds = math.ceil(math.log2(playoff_team_count))
    rounds_left = total_rounds - round_number
    if rounds_left == 0:
        return "Финал"
    if rounds_left == 1:
        return "Полуфинал"
    if rounds_left == 2:
        return "Четвертьфинал"
    return f"Раунд {round_number}"


def build_seeds(teams: Iterable[Any]) -> List[Dict[str, Any]]:
    """Использует официальный playoff seed команды, а не пересчитывает тай-брейк."""
    seeds = []
    for team in teams:
        wins = int(getattr(team, "wins", 0) or 0)
        losses = int(getattr(team, "losses", 0) or 0)
        ties = int(getattr(team, "ties", 0) or 0)
        total_games = wins + losses + ties
        win_pct = (wins + 0.5 * ties) / total_games if total_games else 0.0
        seed = int(getattr(team, "standing", 0) or 0)
        if seed <= 0:
            seed = None

        seeds.append(
            {
                "seed": seed,
                "team_id": team.team_id,
                "team_name": team.team_name,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_pct": round(win_pct * 100, 1),
            }
        )

    seeds.sort(key=lambda item: item["seed"] if item["seed"] is not None else math.inf)
    return seeds


def classify_bracket(
    seed1: Optional[int],
    seed2: Optional[int],
    playoff_team_count: int,
) -> str:
    """Обе команды должны входить в официальный playoff field."""
    if (
        seed1 is not None
        and seed2 is not None
        and seed1 <= playoff_team_count
        and seed2 <= playoff_team_count
    ):
        return "championship"
    return "consolation"


def advance_title_contenders(contenders: set[int], matchups: Iterable[Dict[str, Any]]) -> set[int]:
    """Оставляет победителей матчей чемпионского пути предыдущего раунда."""
    next_contenders: set[int] = set()
    for matchup in matchups:
        team1_id = matchup["team1_id"]
        team2_id = matchup["team2_id"]
        if team1_id not in contenders or team2_id not in contenders:
            continue

        winner = matchup.get("winner")
        if winner == "HOME":
            next_contenders.add(team1_id)
        elif winner == "AWAY":
            next_contenders.add(team2_id)
        else:
            next_contenders.update((team1_id, team2_id))
    return next_contenders


def get_matchup_bracket_type(
    team1_id: int,
    team2_id: int,
    seed1: Optional[int],
    seed2: Optional[int],
    playoff_team_count: int,
    title_contenders: set[int],
) -> str:
    field_type = classify_bracket(seed1, seed2, playoff_team_count)
    if field_type == "consolation":
        return field_type
    if team1_id in title_contenders and team2_id in title_contenders:
        return "championship"
    return "placement"
