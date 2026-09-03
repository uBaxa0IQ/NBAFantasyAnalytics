from types import SimpleNamespace

from web.backend.services.draft import (
    _draft_round_count,
    _planned_team_picks,
    _roster_comparison,
    _round_balanced_roster_comparison,
    _strategy_suggestions,
    get_draft_state,
)
from web.backend.services.draft_advisor import (
    _durability_penalty,
    apply_pick_scores,
    build_pick_advice,
    build_scoring_context,
    normalized_opponent_medians,
    score_draft_pick,
)
from web.backend.services.draft_benchmark import benchmark_adaptive_vs_legacy, benchmark_draft_strategies, benchmark_punt_strategies, evaluate_projected_rosters
from web.backend.services.draft_simulation import _adp_value, _draft_price, _evaluate_rosters, _next_turn_pick, _select_player, annotate_availability, conditional_availability, simulate_draft_market, snake_pick_numbers, unfilled_roster_slots
from web.backend.services.draft_strategy import strategy_library, strategy_probabilities
from web.backend.services import draft_learning
from web.backend.services.espn_market import _serialize_player, blended_market_pick


class FakeRequest:
    def get_league_draft(self):
        return {
            "draftDetail": {
                "drafted": False,
                "inProgress": True,
                "picks": [
                    {"overallPickNumber": number, "roundId": 1, "roundPickNumber": number, "teamId": team, "playerId": 100 + number}
                    for number, team in enumerate((1, 2, 3, 3), start=1)
                ],
            },
            "settings": {
                "draftSettings": {
                    "type": "SNAKE",
                    "pickOrder": [1, 2, 3],
                    "timePerSelection": 60,
                }
            },
        }


class FakeLeagueMetadata:
    def __init__(self):
        self.league = SimpleNamespace(
            espn_request=FakeRequest(),
            player_map={101: "A", 102: "B", 103: "C", 104: "D"},
        )

    def get_teams(self):
        return [
            SimpleNamespace(team_id=team_id, team_name=f"Team {team_id}")
            for team_id in (1, 2, 3)
        ]


def test_live_snake_draft_reports_next_team_after_reversal():
    state = get_draft_state(FakeLeagueMetadata())

    assert state["status"] == "live"
    assert state["pick_count"] == 4
    assert state["next_team_id"] == 2
    assert state["next_overall"] == 5
    assert state["next_round"] == 2
    assert state["next_round_pick"] == 2
    assert state["last_picks"][0]["player_name"] == "D"
    assert state["settings"]["order_known"] is True


def test_snake_plan_handles_both_directions():
    assert _planned_team_picks(2, [1, 2, 3], rounds=4) == [2, 5, 8, 11]


def test_draft_roster_size_comes_from_actual_espn_rounds():
    raw = {
        "draftDetail": {
            "picks": [
                {"roundId": round_id, "playerId": -1}
                for round_id in range(1, 14)
                for _ in range(10)
            ]
        }
    }

    assert _draft_round_count(raw, team_count=10) == 13


def test_predraft_strategy_confidence_is_capped_for_early_roster():
    strategies = _strategy_suggestions({"PTS": 1.0, "BLK": -1.5, "FT%": -0.5}, 2)

    assert strategies
    assert any(strategy["punt_categories"] for strategy in strategies)
    assert all(strategy["confidence"] <= 55 for strategy in strategies)


class UpcomingRequest(FakeRequest):
    def get_league_draft(self):
        data = super().get_league_draft()
        data["draftDetail"].update({"inProgress": False})
        return data


def test_upcoming_draft_explicitly_reports_unknown_order():
    metadata = FakeLeagueMetadata()
    metadata.league.espn_request = UpcomingRequest()

    state = get_draft_state(metadata)

    assert state["status"] == "upcoming"
    assert state["settings"]["order_known"] is False
    assert state["settings"]["ignored_stale_order"] is True
    assert state["next_team_id"] is None
    assert state["pick_count"] == 0
    assert state["ignored_stale_picks"] == 4


def test_market_parser_reads_live_draft_trend_fields():
    row = _serialize_player({
        "id": 1,
        "player": {
            "id": 1,
            "fullName": "Test Player",
            "ownership": {
                "averageDraftPosition": 23.456,
                "averageDraftPositionPercentChange": -0.14,
                "auctionValueAverage": 31.2,
            },
            "draftRanksByRankType": {"ROTO": {"rank": 18}},
        },
    })

    assert row["espn_adp"] == 23.46
    assert row["espn_adp_change"] == -0.14
    assert row["espn_roto_rank"] == 18
    assert row["espn_market_pick"] == 18.55


def test_roto_has_more_weight_in_the_early_lobby_market():
    assert blended_market_pick(33.17, 5) == 7.82
    assert blended_market_pick(136.4, 62) == 88.04
    assert blended_market_pick(50, None) == 50


def test_snake_simulation_uses_full_fourteen_round_plan():
    picks = snake_pick_numbers(slot=4, team_count=14, rounds=14)

    assert len(picks) == 14
    assert picks[:4] == [4, 25, 32, 53]


def test_adp_availability_falls_as_target_pick_moves_later():
    early = conditional_availability(30.0, target_pick=25, current_pick=1)
    late = conditional_availability(30.0, target_pick=40, current_pick=1)

    assert early > late


def test_draft_choice_waits_on_large_reach_when_player_should_survive():
    early_value = {"name": "Available now", "position": "PG", "z_scores": {"PTS": 8.0}}
    future_value = {"name": "Can wait", "position": "SG", "z_scores": {"PTS": 10.0}}

    selected = _select_player(
        [(15.0, early_value), (30.0, future_value)],
        roster=[],
        overall=10,
        own_picks_left=4,
        next_own_pick=20,
    )

    assert selected["name"] == "Available now"


def test_adjacent_snake_picks_share_one_decision_window():
    picks = [1, 28, 29, 56, 57, 84]

    assert _next_turn_pick(picks, 1) == 56
    assert _next_turn_pick(picks, 2) == 56
    assert _next_turn_pick(picks, 3) == 84


def test_price_distinguishes_forced_turn_window_from_avoidable_reach():
    _, forced_type, forced_availability = _draft_price(85, 105.1, 140.0, 112)
    _, reach_type, reach_availability = _draft_price(85, 105.1, 140.0, 92)

    assert forced_availability < 40
    assert forced_type == "turn_window"
    assert reach_availability > 35
    assert reach_type == "reach"


def test_draft_choice_softly_penalizes_extremely_low_games_played():
    healthy = {"name": "Healthy", "position": "PG", "games_played": 70, "z_scores": {"PTS": 5.0}}
    risky = {"name": "Risky", "position": "SG", "games_played": 10, "z_scores": {"PTS": 5.5}}

    selected = _select_player([(10.0, healthy), (10.0, risky)], [], 10, 4, next_own_pick=20)

    assert selected["name"] == "Healthy"


def test_slot_simulation_returns_round_by_round_roster():
    players = [
        {
            "name": f"Player {index}",
            "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
            "espn_adp": float(index),
            "games_played": 60 + index % 20,
            "score": 100 - index,
        }
        for index in range(1, 50)
    ]

    simulation = simulate_draft_market(players, team_count=3, rounds=4)
    first_slot = simulation["slot_results"][0]

    assert first_slot["picks"] == [1, 6, 7, 12]
    assert len(first_slot["round_targets"]) == 4
    assert len(first_slot["projected_roster"]) == 4
    assert all("games_played" in player for player in first_slot["projected_roster"])


def test_selected_slot_runs_deep_full_league_analysis():
    players = [
        {
            "name": f"Player {index}",
            "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
            "espn_adp": float(index),
            "games_played": 60 + index % 20,
            "score": 100 - index,
            "general_z": 10 - index / 10,
            "z_scores": {category: (index % 7 - 3) / 3 for category in ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")},
        }
        for index in range(1, 50)
    ]

    simulation = simulate_draft_market(players, team_count=3, rounds=4, selected_slot=2)
    result = simulation["slot_result"]

    assert simulation["mode"] == "selected_slot"
    assert simulation["runs"] == 240
    assert 0 <= result["average_category_wins"] <= 11
    assert 1 <= result["average_league_rank"] <= 3
    assert set(result["category_ranks"]) == set(players[0]["z_scores"])
    assert all(player["selection_frequency"] <= player["availability_frequency"] for player in result["projected_roster"])


def test_constructor_roster_only_simulates_remaining_roster_spots():
    categories = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")
    players = [
        {
            "name": f"Available {index}",
            "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
            "espn_adp": float(index),
            "games_played": 70,
            "z_scores": {category: (index % 5 - 2) / 2 for category in categories},
        }
        for index in range(1, 50)
    ]
    preset = [
        {"name": "Preset 1", "position": "PG", "games_played": 70, "z_scores": {category: 0 for category in categories}},
        {"name": "Preset 2", "position": "C", "games_played": 70, "z_scores": {category: 1 for category in categories}},
    ]

    result = simulate_draft_market(players, team_count=3, rounds=4, selected_slot=1, own_existing_roster=preset)["slot_result"]

    assert len(result["projected_roster"]) == 2
    assert [row["round"] for row in result["projected_roster"]] == [3, 4]


def test_roster_comparison_ranks_assembled_teams():
    categories = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")
    profiles = {
        1: [{"z_scores": {category: 2 for category in categories}}],
        2: [{"z_scores": {category: 0 for category in categories}}],
        3: [{"z_scores": {category: -1 for category in categories}}],
    }

    comparison = _roster_comparison(profiles, {1: "One", 2: "Two", 3: "Three"}, 2)

    assert comparison["league_rank"] == 2
    assert comparison["teams"][0]["team_name"] == "One"


def test_round_balanced_comparison_ignores_partial_next_round():
    categories = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")
    profiles = {
        1: [
            {"z_scores": {category: 1 for category in categories}},
            {"z_scores": {category: 10 for category in categories}},
        ],
        2: [{"z_scores": {category: 2 for category in categories}}],
        3: [{"z_scores": {category: 0 for category in categories}}],
    }

    result = _round_balanced_roster_comparison(
        profiles,
        {1: "One", 2: "Two", 3: "Three"},
        main_team_id=1,
        pick_count=4,
        team_count=3,
    )

    assert result["completed_rounds"] == 1
    assert result["comparison"]["league_rank"] == 2
    assert all(team["roster_size"] == 1 for team in result["comparison"]["teams"])


def test_adp_value_ignores_censored_late_market_tail():
    assert _adp_value(52, 60.0, 140.0) == -8.0
    assert _adp_value(160, 139.5, 140.0) is None
    assert _adp_value(196, 138.9, 140.8) is None
    assert _adp_value(196, 135.8, 140.8) is None
    assert _adp_value(141, 135.8, 140.8) == 5.2


def test_known_live_slot_only_projects_remaining_turns():
    categories = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")
    players = [
        {
            "name": f"Available {index}",
            "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
            "espn_adp": float(index),
            "games_played": 70,
            "general_z": 5 - index / 20,
            "z_scores": {category: (index % 5 - 2) / 2 for category in categories},
        }
        for index in range(1, 50)
    ]
    existing = {slot: [{"name": f"Drafted {slot}", "position": "C", "games_played": 70, "z_scores": {category: 0 for category in categories}}] for slot in (1, 2, 3)}

    simulation = simulate_draft_market(
        players,
        team_count=3,
        rounds=4,
        pick_order=(10, 20, 30),
        team_id=20,
        current_pick=4,
        existing_rosters_by_slot=existing,
    )

    assert simulation["mode"] == "known_order"
    assert simulation["slot"] == 2
    assert [round_result["pick"] for round_result in simulation["slot_result"]["round_targets"]] == [5, 8, 11]


class CompletedRequest(FakeRequest):
    def get_league_draft(self):
        data = super().get_league_draft()
        data["draftDetail"].update({"inProgress": False, "drafted": True})
        return data

    def get_league(self):
        return {
            "schedule": [{
                "winner": "UNDECIDED",
                "home": {"gamesPlayed": 0, "totalPoints": 0, "cumulativeScore": {"scoreByStat": {}}},
                "away": {"gamesPlayed": 0, "totalPoints": 0, "cumulativeScore": {"scoreByStat": {}}},
            }]
        }


def test_completed_draft_before_scoring_is_postdraft_phase():
    metadata = FakeLeagueMetadata()
    metadata.league.espn_request = CompletedRequest()
    metadata.league.scoringPeriodId = 1

    state = get_draft_state(metadata)

    assert state["status"] == "completed"
    assert state["postdraft"] is True
    assert state["phase"] == "postdraft"


def test_zero_score_tie_placeholders_do_not_start_the_season():
    metadata = FakeLeagueMetadata()
    request = CompletedRequest()
    request.get_league = lambda: {
        "schedule": [{
            "winner": "UNDECIDED",
            "home": {"gamesPlayed": 0, "totalPoints": 0, "cumulativeScore": {"scoreByStat": {"0": {"result": "TIE", "score": 0}}}},
            "away": {"gamesPlayed": 0, "totalPoints": 0, "cumulativeScore": {"scoreByStat": {"0": {"result": "TIE", "score": 0}}}},
        }]
    }
    metadata.league.espn_request = request

    state = get_draft_state(metadata)

    assert state["season_started"] is False
    assert state["postdraft"] is True
    assert state["phase"] == "postdraft"


def test_placeholder_player_ids_are_not_counted_as_completed_picks():
    metadata = FakeLeagueMetadata()
    raw = metadata.league.espn_request.get_league_draft()
    raw["draftDetail"]["picks"] = [
        {"overallPickNumber": number, "roundId": 1, "roundPickNumber": number, "teamId": number, "playerId": -1}
        for number in (1, 2, 3)
    ]
    metadata.league.espn_request.get_league_draft = lambda: raw

    state = get_draft_state(metadata)

    assert state["pick_count"] == 0
    assert state["ignored_stale_picks"] == 3
    assert state["next_overall"] == 1
    assert state["next_team_id"] == 1


class ActiveSeasonRequest(CompletedRequest):
    def get_league(self):
        data = super().get_league()
        data["schedule"][0]["home"]["gamesPlayed"] = 1
        return data


def test_completed_draft_enters_season_only_after_real_matchup_activity():
    metadata = FakeLeagueMetadata()
    metadata.league.espn_request = ActiveSeasonRequest()

    state = get_draft_state(metadata)

    assert state["season_started"] is True
    assert state["postdraft"] is False
    assert state["phase"] == "season"


CATEGORIES = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "DD", "FG%", "FT%", "3PT%", "A/TO")


def _z(**overrides):
    profile = {category: 0.0 for category in CATEGORIES}
    profile.update(overrides)
    return profile


def _player(name, position="PG", adp=40, **z_overrides):
    return {
        "name": name,
        "position": position,
        "espn_adp": float(adp),
        "espn_market_pick": float(adp),
        "games_played": 70,
        "z_scores": _z(**z_overrides),
        "total_z": sum(_z(**z_overrides).values()),
    }


def test_punt_ignores_punted_category_even_if_it_is_huge():
    star_ft = _player("FT specialist", adp=20, **{"FT%": 8.0, "PTS": 1.0})
    punt_fit = _player("Punt fit", adp=20, **{"FT%": -3.0, "PTS": 3.0, "REB": 2.5, "STL": 2.0})
    context = build_scoring_context(
        roster=[],
        remaining=[star_ft, punt_fit],
        eval_pick=20,
        is_on_the_clock=True,
        punt_categories=("FT%",),
        team_count=10,
        rounds=14,
    )

    assert score_draft_pick(punt_fit, context)["score"] > score_draft_pick(star_ft, context)["score"]


def test_on_the_clock_takes_player_who_will_not_survive():
    falling_star = _player("Star now", adp=12, PTS=6.0, REB=2.0, AST=2.0)
    later_value = _player("Later value", adp=36, PTS=7.0, REB=2.5, AST=2.5)
    context = build_scoring_context(
        roster=[],
        remaining=[falling_star, later_value],
        eval_pick=14,
        next_own_pick=35,
        is_on_the_clock=True,
        own_picks_left=8,
        team_count=10,
        rounds=14,
    )
    annotate_availability([falling_star, later_value], 14, 35, 14)
    apply_pick_scores([falling_star, later_value], context)

    assert falling_star["score"] > later_value["score"]
    assert falling_star["draft_action"] == "брать сейчас"


def test_off_the_clock_does_not_rank_a_gone_star_first():
    gone_star = _player("Will be gone", adp=8, PTS=9.0, REB=3.0, AST=3.0)
    reachable = _player("Reachable", adp=48, PTS=4.0, REB=1.5, AST=1.5)
    players = [gone_star, reachable]
    annotate_availability(players, target_pick=46, following_pick=55, current_pick=20)
    context = build_scoring_context(
        roster=[],
        remaining=players,
        eval_pick=46,
        next_own_pick=55,
        is_on_the_clock=False,
        picks_until_turn=26,
        own_picks_left=8,
        team_count=10,
        rounds=14,
    )
    apply_pick_scores(players, context)

    assert reachable["availability_probability"] > gone_star["availability_probability"]
    assert reachable["score"] > gone_star["score"]
    advice = build_pick_advice(players, context)
    assert advice["primary"]["name"] == "Reachable"


def test_leverage_prefers_category_flip_over_stacked_points():
    roster = [_player("Scorer", PTS=4.0, STL=-1.2)]
    opponents = [[_player("Opp A", PTS=1.5, STL=1.0)], [_player("Opp B", PTS=1.2, STL=0.8)]]
    stack_pts = _player("More points", adp=40, PTS=3.5, STL=-0.4)
    steal_specialist = _player("Steals", adp=40, PTS=0.4, STL=2.4)
    context = build_scoring_context(
        roster=roster,
        remaining=[stack_pts, steal_specialist],
        eval_pick=40,
        is_on_the_clock=True,
        own_picks_left=8,
        team_count=3,
        rounds=8,
        opponent_rosters=opponents,
    )
    steal_score = score_draft_pick(steal_specialist, context)
    points_score = score_draft_pick(stack_pts, context)

    assert steal_score["leverage"] > points_score["leverage"]
    assert "STL" in steal_score["flips"] or steal_score["score"] > points_score["score"]


def test_evaluate_rosters_with_punts_still_counts_sacrificed_category():
    categories = CATEGORIES
    strong_punt = {
        1: [{"z_scores": {category: (4 if category != "FT%" else -8) for category in categories}}],
        2: [{"z_scores": {category: 1 for category in categories}}],
        3: [{"z_scores": {category: 0 for category in categories}}],
    }

    balanced = _evaluate_rosters(strong_punt, 1)
    punted = _evaluate_rosters(strong_punt, 1, ("FT%",))

    assert punted == balanced
    assert punted["category_wins"] <= len(categories)


def test_partial_opponent_rosters_are_normalized_to_same_size():
    medians = normalized_opponent_medians(
        [
            [{"z_scores": {"PTS": 2}}],
            [{"z_scores": {"PTS": 1}}, {"z_scores": {"PTS": 1}}],
        ],
        target_size=2,
    )

    assert medians["PTS"] == 3


def test_durability_penalty_is_continuous_at_zero_games():
    zero = _durability_penalty({"games_played": 0, "injury_status": "ACTIVE"})
    one = _durability_penalty({"games_played": 1, "injury_status": "ACTIVE"})

    assert zero >= one
    assert zero - one < 0.1


def test_projected_evaluator_counts_punt_category_and_projected_volume():
    rosters = {
        1: [{"stats": {"GP": 80, "PTS": 10, "FGM": 4, "FGA": 10}}],
        2: [{"stats": {"GP": 40, "PTS": 15, "FGM": 9, "FGA": 20}}],
    }

    result = evaluate_projected_rosters(rosters, 1)

    assert result["category_wins"] == 1 + (len(CATEGORIES) - 2) * 0.5
    assert result["category_totals"]["PTS"] == 800
    assert result["category_totals"]["FG%"] == 0.4


def test_paired_benchmark_compares_model_and_punt_to_roto():
    categories = tuple(CATEGORIES)
    players = [
        {
            "player_id": index,
            "name": f"Projected {index}",
            "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
            "eligible_slots": [("PG", "SG", "SF", "PF", "C")[index % 5]],
            "espn_adp": float(index),
            "espn_market_pick": float(index),
            "espn_roto_rank": index,
            "games_played": 70,
            "stats": {
                "GP": 70,
                "PTS": 30 - index / 10,
                "REB": 3 + index % 8,
                "AST": 2 + index % 6,
                "STL": 1 + index % 3 / 10,
                "BLK": 0.5 + index % 4 / 10,
                "3PM": 1 + index % 5 / 10,
                "DD": index % 2 / 10,
                "FGM": 5,
                "FGA": 10 + index % 3,
                "FTM": 4,
                "FTA": 5 + index % 2,
                "3PA": 4 + index % 3,
                "TO": 2,
            },
            "z_scores": {category: (30 - index) / 20 for category in categories},
        }
        for index in range(1, 37)
    ]

    result = benchmark_draft_strategies(players, 3, 4, runs_per_slot=2)

    assert result["total_paired_scenarios"] == 6
    assert [row["id"] for row in result["strategies"]] == [
        "roto", "model_balanced", "model_punt_fgpct",
    ]
    assert all(row["baseline"] == "roto" for row in result["comparisons"])
    assert all(len(row["delta_category_wins_ci95"]) == 2 for row in result["comparisons"])


def test_pick_advice_groups_take_now_and_wait_lanes():
    take = _player("Take", adp=10, PTS=5.0)
    wait = _player("Wait", adp=40, PTS=3.0)
    take["draft_action"] = "брать сейчас"
    take["next_round_probability"] = 10
    take["availability_probability"] = 100
    wait["draft_action"] = "можно ждать"
    wait["next_round_probability"] = 85
    wait["availability_probability"] = 100
    context = build_scoring_context(
        roster=[],
        remaining=[take, wait],
        eval_pick=12,
        next_own_pick=37,
        is_on_the_clock=True,
        team_count=10,
        rounds=14,
    )
    apply_pick_scores([take, wait], context)
    advice = build_pick_advice([take, wait], context)

    assert advice["primary"]["name"] in {"Take", "Wait"}
    displayed = [advice["primary"], *advice["take_now"], *advice["wait"], *advice["fallback"]]
    assert any(player["name"] == "Take" for player in displayed)
    assert any(player["name"] == "Wait" for player in displayed)
    assert len(displayed) <= 6
    assert advice["is_on_the_clock"] is True


def test_exact_roster_slots_respect_multi_position_eligibility():
    roster = [
        {"name": "Combo", "position": "PG", "eligible_slots": ["PG", "SG", "G", "UT", "BE"]},
        {"name": "Wing", "position": "SF", "eligible_slots": ["SF", "F", "UT", "BE"]},
    ]

    missing = unfilled_roster_slots(roster, ("PG", "SG", "SF", "PF", "C", "G", "F", "UT", "BE"))

    assert len(missing) == 5
    assert "PG" not in missing
    assert "SF" not in missing
    assert {"PF", "C", "G", "F"}.issubset(set(missing))


def test_exhaustive_punt_benchmark_counts_zero_one_and_two_category_strategies():
    categories = ("PTS", "REB", "AST")
    players = [
        {
            "player_id": index,
            "name": f"Punt pool {index}",
            "position": "G" if index % 2 else "F",
            "eligible_slots": ["G", "UT", "BE"] if index % 2 else ["F", "UT", "BE"],
            "espn_market_pick": float(index),
            "espn_roto_rank": index,
            "stats": {"GP": 70, "PTS": 10 + index, "REB": 3 + index % 4, "AST": 2 + index % 5},
        }
        for index in range(1, 17)
    ]

    result = benchmark_punt_strategies(
        players, 2, 3, categories, max_punts=2, roster_slots=("G", "F", "UT"),
        screening_runs=1, deep_runs=2, finalist_count=3,
    )

    assert result["strategies_screened"] == 7
    assert result["max_punts"] == 2
    assert any(row["id"] == "balanced" for row in result["finalists"])


def test_adaptive_strategy_starts_flexible_and_probabilities_sum_to_one():
    categories = ("FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "PTS")

    rows = strategy_probabilities([], categories, 13)

    assert rows[0]["id"] == "balanced"
    assert abs(sum(row["probability"] for row in rows) - 1.0) < 1e-9
    assert len(strategy_library(categories)) == 6


def test_adaptive_projected_marginal_prefers_season_volume():
    high_volume = _player("High volume", adp=10, PTS=1.0)
    low_volume = _player("Low volume", adp=10, PTS=1.0)
    high_volume.update({"stats": {"GP": 80, "PTS": 20}, "games_played": 80})
    low_volume.update({"stats": {"GP": 20, "PTS": 20}, "games_played": 20})

    selected = _select_player(
        [(10.0, low_volume), (10.0, high_volume)], [], 10, 3,
        categories=("PTS",), policy_mode="adaptive",
    )

    assert selected["name"] == "High volume"


def test_population_self_play_compares_adaptive_and_legacy_policies():
    categories = ("PTS", "REB", "AST")
    players = [
        {
            "player_id": index,
            "name": f"Self play {index}",
            "position": "G" if index % 2 else "F",
            "eligible_slots": ["G", "UT"] if index % 2 else ["F", "UT"],
            "espn_market_pick": float(index),
            "espn_adp": float(index),
            "espn_roto_rank": index,
            "stats": {"GP": 60 + index % 10, "PTS": 8 + index, "REB": 2 + index % 5, "AST": 1 + index % 6},
        }
        for index in range(1, 13)
    ]

    result = benchmark_adaptive_vs_legacy(
        players, 2, 2, categories, roster_slots=("G", "F"), runs_per_slot=1,
    )

    assert result["paired_scenarios"] == 2
    assert {row["id"] for row in result["strategies"]} == {
        "legacy_balanced", "legacy_best_fixed", "adaptive_heuristic", "adaptive",
    }
    assert result["comparisons_to_adaptive_heuristic"][0]["strategy"] == "adaptive"
    assert result["comparisons_to_legacy_fixed"][0]["strategy"] == "adaptive"


def test_live_decision_dataset_records_and_resolves_actual_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(draft_learning, "DB_PATH", tmp_path / "draft_learning.db")
    draft_learning.record_live_decision(
        league_id=1, season=2027, team_id=7, pick_count=10, target_overall=11,
        roster=[], advice={"primary": {"name": "Recommended"}},
        adaptive_strategy={"strategies": []}, completed_picks=[],
    )
    draft_learning.record_live_decision(
        league_id=1, season=2027, team_id=7, pick_count=11, target_overall=30,
        roster=[], advice={}, adaptive_strategy={},
        completed_picks=[{
            "overallPickNumber": 11, "teamId": 7, "playerId": 99,
            "player_name": "Actually drafted",
        }],
    )

    stats = draft_learning.learning_dataset_stats()

    assert stats["decisions"] == 2
    assert stats["resolved"] == 1


def test_select_player_uses_punt_fit_instead_of_raw_total_z():
    raw_star = {"name": "Raw", "position": "SG", "games_played": 70, "z_scores": _z(**{"FT%": 7.0, "PTS": 1.0})}
    fit = {"name": "Fit", "position": "PG", "games_played": 70, "z_scores": _z(**{"PTS": 3.0, "AST": 2.5, "STL": 1.5, "FT%": -2.0})}

    selected = _select_player(
        [(20.0, raw_star), (20.0, fit)],
        roster=[],
        overall=20,
        own_picks_left=8,
        next_own_pick=41,
        punt_categories=("FT%",),
    )

    assert selected["name"] == "Fit"
