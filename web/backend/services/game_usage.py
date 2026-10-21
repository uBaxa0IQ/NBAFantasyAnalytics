"""Count fantasy player-games from ESPN's daily lineups and NBA schedule."""

from datetime import datetime
from time import monotonic

from core.projection import get_matchup_scoring_periods, optimize_daily_lineup
from core.roster_rules import league_slots


def _player_row(player):
    return {
        "name": player.name,
        "position": getattr(player, "position", ""),
        "eligible_slots": getattr(player, "eligibleSlots", []),
        "lineup_value": 1,
    }


def _played(player, day):
    stats = (getattr(player, "stats", {}) or {}).get(str(day), {})
    return float((stats.get("total") or {}).get("GP", 0) or 0) > 0


def _game_on_day(player, day, *, unstarted=False):
    game = (getattr(player, "schedule", {}) or {}).get(str(day))
    if not game:
        return False
    if not unstarted:
        return True
    game_date = game.get("date")
    if not isinstance(game_date, datetime):
        return False
    now = datetime.now(game_date.tzinfo) if game_date.tzinfo else datetime.now()
    return game_date > now


def _available(player):
    return getattr(player, "lineupSlot", "") != "IR" and not (
        getattr(player, "injured", False)
        and getattr(player, "injuryStatus", "ACTIVE") == "OUT"
    )


def _max_games(players, slots):
    return len(optimize_daily_lineup([_player_row(player) for player in players], slots, fill_slots=True)["starters"])


def get_week_game_usage(league_meta, team_ids):
    """Return counted games and projected week totals for the matchup teams."""
    league = league_meta.league
    week = int(league.currentMatchupPeriod)
    current_day = int(league.scoringPeriodId)
    selected_ids = tuple(sorted(int(team_id) for team_id in team_ids))
    cache_key = (week, current_day, selected_ids)
    cache = getattr(league_meta, "_game_usage_cache", None)
    if cache and cache[0] == cache_key and monotonic() - cache[1] < 60:
        return cache[2]

    days = get_matchup_scoring_periods(league, week)
    slots = league_slots(league_meta)
    active_slots = set(slots)
    teams = [team for team in league_meta.get_teams() if team.team_id in selected_ids]
    rows = {
        team.team_id: {
            "played": 0,
            "projected_total": 0,
        }
        for team in teams
    }
    current_lineups = {}

    for day in days:
        if day > current_day:
            continue
        boxes = league.box_scores(matchup_period=week, scoring_period=day, matchup_total=False)
        for box in boxes:
            for team, lineup in ((box.home_team, box.home_lineup), (box.away_team, box.away_lineup)):
                team_id = getattr(team, "team_id", None)
                if team_id not in rows:
                    continue
                played_players = [player for player in lineup if _played(player, day)]
                actual = sum(getattr(player, "slot_position", "") in active_slots for player in played_players)
                rows[team_id]["played"] += actual
                if day == current_day:
                    current_lineups[team_id] = played_players

    for team in teams:
        row = rows[team.team_id]
        roster = [player for player in team.roster if _available(player)]
        remaining = 0
        for day in days:
            if day < current_day:
                continue
            if day == current_day:
                played_players = current_lineups.get(team.team_id, [])
                used_slots = [player.slot_position for player in played_players if player.slot_position in active_slots]
                open_slots = list(slots)
                for slot in used_slots:
                    if slot in open_slots:
                        open_slots.remove(slot)
                played_ids = {player.playerId for player in played_players}
                candidates = [
                    player for player in roster
                    if player.playerId not in played_ids and _game_on_day(player, day, unstarted=True)
                ]
            else:
                open_slots = slots
                candidates = [player for player in roster if _game_on_day(player, day)]
            remaining += _max_games(candidates, open_slots)
        row["projected_total"] = row["played"] + remaining

    league_meta._game_usage_cache = (cache_key, monotonic(), rows)
    return rows
