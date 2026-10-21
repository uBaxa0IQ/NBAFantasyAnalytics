from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from web.backend.services import game_usage


def player(name, slot, eligible, *, played=False, schedule=None):
    return SimpleNamespace(
        name=name,
        playerId=name,
        position=eligible[0],
        eligibleSlots=eligible,
        slot_position=slot,
        lineupSlot=slot,
        injuryStatus="ACTIVE",
        injured=False,
        schedule=schedule or {},
        stats={"1": {"total": {"GP": 1}}} if played else {},
    )


class GameUsageTests(TestCase):
    def test_only_active_games_count_and_open_slots_can_fill_later(self):
        later = datetime.now() + timedelta(hours=2)
        starter = player("starter", "PG", ["PG"], played=True)
        benched_center = player("bench", "BE", ["C"], played=True)
        extra_guard = player("extra", "BE", ["PG"], played=True)
        upcoming_center = player("upcoming", "BE", ["C"], schedule={"1": {"date": later}})
        team = SimpleNamespace(team_id=1, team_name="A", roster=[starter, benched_center, extra_guard, upcoming_center])
        opponent = SimpleNamespace(team_id=2, team_name="B", roster=[])
        box = SimpleNamespace(home_team=team, away_team=opponent,
                              home_lineup=[starter, benched_center, extra_guard, upcoming_center],
                              away_lineup=[])
        league = SimpleNamespace(currentMatchupPeriod=1, scoringPeriodId=1,
                                 box_scores=lambda **_: [box])
        meta = SimpleNamespace(league=league, get_teams=lambda: [team, opponent])

        with patch.object(game_usage, "get_matchup_scoring_periods", return_value=[1, 2]), \
             patch.object(game_usage, "league_slots", return_value=("PG", "C")):
            rows = game_usage.get_week_game_usage(meta, (1, 2))
        mine = rows[1]

        self.assertEqual(mine["played"], 1)
        self.assertEqual(mine["projected_total"], 2)
