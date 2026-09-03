"""Deterministic Monte Carlo helpers for snake-draft planning."""

from __future__ import annotations

from collections import Counter
import math
import random

from core.config import CATEGORIES
from core.projection import can_play_slot

POSITIONS = ("PG", "SG", "SF", "PF", "C")
DEFAULT_DRAFT_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F")
FLEX_DRAFT_SLOTS = {"UT", "BE", "IR", "", "Rookie"}


def unfilled_roster_slots(roster, roster_slots=None):
    """Return constrained ESPN slots not covered by an optimal assignment."""
    slots = tuple(slot for slot in (roster_slots or DEFAULT_DRAFT_SLOTS) if slot not in FLEX_DRAFT_SLOTS)
    if not slots:
        return ()
    masks = {0}
    for player in roster or ():
        next_masks = set(masks)
        for mask in masks:
            for index, slot in enumerate(slots):
                bit = 1 << index
                if not mask & bit and can_play_slot(player, slot):
                    next_masks.add(mask | bit)
        masks = next_masks
    best = max(masks, key=int.bit_count)
    return tuple(slot for index, slot in enumerate(slots) if not best & (1 << index))
def snake_pick_numbers(slot: int, team_count: int, rounds: int = 14):
    return [
        round_index * team_count + (slot if round_index % 2 == 0 else team_count + 1 - slot)
        for round_index in range(rounds)
    ]


def _market_sigma(adp: float):
    return max(3.0, min(18.0, 2.5 + 0.12 * adp))


def _market_position(player):
    value = player.get("espn_market_pick")
    if value is None:
        value = player.get("espn_adp")
    return float(value) if value is not None else None


def _adp_value(overall_pick: int, adp: float | None, adp_ceiling: float):
    """Return pick minus ADP, unless the source has censored the late-player tail."""
    if adp is None:
        return None
    late_tail_threshold = adp_ceiling - max(10.0, adp_ceiling * 0.07)
    if overall_pick > adp_ceiling + 14 and adp >= late_tail_threshold:
        return None
    return round(overall_pick - adp, 1)


def _next_turn_pick(picks, index):
    """Skip an adjacent snake pick: the pair belongs to the same draft turn."""
    next_index = index + 1
    while next_index < len(picks) and picks[next_index] == picks[next_index - 1] + 1:
        next_index += 1
    return picks[next_index] if next_index < len(picks) else None


def _draft_price(overall_pick, adp, adp_ceiling, next_turn_pick=None):
    value = _adp_value(overall_pick, adp, adp_ceiling)
    next_turn_availability = conditional_availability(adp, next_turn_pick, overall_pick)
    if value is None:
        price_type = "unknown"
    elif value >= 5:
        price_type = "value"
    elif value >= -5:
        price_type = "market"
    elif next_turn_availability is not None and next_turn_availability < 40:
        price_type = "turn_window"
    else:
        price_type = "reach"
    return value, price_type, next_turn_availability


def _survival(adp: float | None, overall_pick: int | None):
    """Chance that a player with this ADP is still present at an overall pick."""
    if adp is None or overall_pick is None or overall_pick <= 1:
        return 1.0 if overall_pick and overall_pick <= 1 else None
    sigma = _market_sigma(adp)
    z = (overall_pick - 0.5 - adp) / sigma
    return max(0.0, min(1.0, 0.5 * math.erfc(z / math.sqrt(2))))


def conditional_availability(adp: float | None, target_pick: int | None, current_pick: int = 1):
    if adp is None or target_pick is None:
        return None
    # The player is on the board now, so remaining life is measured from this pick,
    # not from the original ADP clock. Fallen stars therefore expire quickly.
    implied_adp = max(float(adp), float(current_pick or 1))
    target = _survival(implied_adp, target_pick)
    current = _survival(implied_adp, max(1, current_pick))
    if target is None or current in (None, 0):
        return None
    return round(max(0.0, min(1.0, target / current)) * 100)


def annotate_availability(players, target_pick, following_pick=None, current_pick=1):
    for player in players:
        market_pick = _market_position(player)
        probability = conditional_availability(market_pick, target_pick, current_pick)
        next_probability = conditional_availability(market_pick, following_pick, current_pick)
        player["availability_probability"] = probability
        player["next_round_probability"] = next_probability
        if target_pick is None:
            player["availability"] = "очередь неизвестна"
        elif probability is None:
            player["availability"] = "нет данных ESPN"
        elif probability >= 70:
            player["availability"] = "вероятно доступен"
        elif probability >= 35:
            player["availability"] = "на границе"
        else:
            player["availability"] = "вряд ли доживёт"

        if target_pick is None:
            player["draft_action"] = "порядок неизвестен"
        elif target_pick <= current_pick:
            if next_probability is None:
                player["draft_action"] = "оценить сейчас"
            elif next_probability < 35:
                player["draft_action"] = "брать сейчас"
            elif next_probability >= 70:
                player["draft_action"] = "можно ждать"
            else:
                player["draft_action"] = "риск ожидания"
        elif probability is not None and probability < 35:
            player["draft_action"] = "нужен фолл"
        else:
            player["draft_action"] = "цель на ход"
    return players


def _slot_at_pick(overall, team_count):
    round_index, round_pick = divmod(overall - 1, team_count)
    return round_pick + 1 if round_index % 2 == 0 else team_count - round_pick


def _player_value(player, punt_categories=()):
    z_scores = player.get("z_scores") or {}
    if z_scores:
        return sum(value for category, value in z_scores.items() if category not in punt_categories)
    return float(player.get("general_z", player.get("score", 0)))


def _select_player(
    market_order,
    roster,
    overall,
    own_picks_left,
    next_own_pick=None,
    punt_categories=(),
    opponent_rosters=(),
    rounds=14,
    team_count=10,
    roster_slots=None,
    categories=None,
    policy_mode="legacy",
):
    from .draft_advisor import build_scoring_context, score_draft_pick

    window_size = 18
    window = market_order[:max(8, min(window_size, len(market_order)))]
    missing_positions = set(unfilled_roster_slots(roster, roster_slots))
    if missing_positions and own_picks_left <= len(missing_positions):
        forced_window = [
            item for item in market_order
            if any(can_play_slot(item[1], position) for position in missing_positions)
        ][:window_size]
        if forced_window:
            window = forced_window

    remaining = [player for _, player in market_order]
    context = build_scoring_context(
        roster=roster,
        remaining=remaining,
        eval_pick=overall,
        next_own_pick=next_own_pick,
        is_on_the_clock=True,
        picks_until_turn=0,
        own_picks_left=own_picks_left,
        punt_categories=punt_categories,
        team_count=team_count,
        rounds=rounds,
        opponent_rosters=opponent_rosters,
        roster_slots=roster_slots,
        categories=categories,
    )
    if policy_mode in {"adaptive", "adaptive_heuristic"}:
        from .draft_strategy import adaptive_rank_window
        ranked, _ = adaptive_rank_window(window, context)
        if ranked:
            adaptive_players = [player for _, player, _ in ranked]
            if policy_mode == "adaptive":
                from .draft_ml.inference import maybe_apply_learned_rerank
                maybe_apply_learned_rerank(adaptive_players, context, limit=len(adaptive_players))
            return adaptive_players[0]
    return max(window, key=lambda item: score_draft_pick(item[1], context, market_pick=item[0])["score"])[1]


def _evaluate_rosters(team_rosters, own_slot, punt_categories=()):
    """Evaluate real league results; punts affect selection, never league rules."""
    active = list(CATEGORIES)
    category_totals = {
        slot: {
            category: sum((player.get("z_scores") or {}).get(category, 0) for player in roster)
            for category in active
        }
        for slot, roster in team_rosters.items()
    }
    matchup_scores = {slot: 0.0 for slot in team_rosters}
    slots = list(team_rosters)
    for left_index, left in enumerate(slots):
        for right in slots[left_index + 1:]:
            for category in active:
                left_value = category_totals[left][category]
                right_value = category_totals[right][category]
                if left_value > right_value + 1e-9:
                    matchup_scores[left] += 1
                elif right_value > left_value + 1e-9:
                    matchup_scores[right] += 1
                else:
                    matchup_scores[left] += 0.5
                    matchup_scores[right] += 0.5
    opponent_count = max(1, len(slots) - 1)
    matchup_scores = {slot: score / opponent_count for slot, score in matchup_scores.items()}
    own_score = matchup_scores[own_slot]
    league_rank = 1 + sum(score > own_score + 1e-9 for slot, score in matchup_scores.items() if slot != own_slot)
    display_totals = {
        slot: {
            category: sum((player.get("z_scores") or {}).get(category, 0) for player in roster)
            for category in CATEGORIES
        }
        for slot, roster in team_rosters.items()
    }
    category_ranks = {
        category: 1 + sum(
            totals[category] > display_totals[own_slot][category] + 1e-9
            for slot, totals in display_totals.items()
            if slot != own_slot
        )
        for category in CATEGORIES
    }
    opponent_average = {
        category: sum(totals[category] for slot, totals in display_totals.items() if slot != own_slot) / opponent_count
        for category in CATEGORIES
    }
    return {
        "category_wins": matchup_scores[own_slot],
        "league_rank": league_rank,
        "category_ranks": category_ranks,
        "category_margin": {
            category: display_totals[own_slot][category] - opponent_average[category]
            for category in CATEGORIES
        },
    }


def _simulate_slot(
    players,
    slot,
    team_count,
    rounds,
    runs,
    current_pick,
    seed,
    existing_rosters_by_slot=None,
    own_existing_roster=None,
    playoff_team_count=8,
    own_punt_categories=(),
    roster_slots=None,
    evaluation_mode="z_score",
    categories=None,
    include_samples=False,
    own_policy="legacy",
):
    planned = snake_pick_numbers(slot, team_count, rounds)
    preset_own_roster = list(own_existing_roster or ())
    preset_own_count = len(preset_own_roster) if current_pick <= 1 else 0
    first_pick_counter = Counter()
    roster_counter = Counter()
    future_picks = [
        pick for index, pick in enumerate(planned)
        if pick >= current_pick and index >= preset_own_count
    ]
    round_counters = [Counter() for _ in future_picks]
    availability_counters = [Counter() for _ in future_picks]
    total_score = 0.0
    outcomes = []

    usable = [player for player in players if _market_position(player) is not None]
    if not usable:
        return {"slot": slot, "average_score": 0.0, "first_targets": [], "core_targets": [], "round_targets": [], "projected_roster": []}
    market_ceiling = max(_market_position(player) for player in usable)

    for run in range(runs):
        board = []
        for player in usable:
            market_average = _market_position(player)
            identity = player.get("player_id") or player.get("name")
            player_rng = random.Random(f"{seed}:{run}:{identity}")
            market_pick = max(1.0, player_rng.gauss(market_average, _market_sigma(market_average)))
            board.append([market_pick, player])
        remaining = {id(item[1]): item for item in board}
        team_rosters = {
            team_slot: list((existing_rosters_by_slot or {}).get(team_slot, ()))
            for team_slot in range(1, team_count + 1)
        }
        if preset_own_roster:
            team_rosters[slot] = list(preset_own_roster)
        own_future_roster = []

        for overall in range(current_pick, team_count * rounds + 1):
            if not remaining:
                break
            market_order = sorted(remaining.values(), key=lambda item: item[0])
            drafting_slot = _slot_at_pick(overall, team_count)
            roster = team_rosters[drafting_slot]
            slot_future_picks = [pick for pick in snake_pick_numbers(drafting_slot, team_count, rounds) if pick >= overall]
            next_turn_pick = _next_turn_pick(slot_future_picks, 0)
            opponents = [team_rosters[team_slot] for team_slot in team_rosters if team_slot != drafting_slot]
            select_kwargs = {
                "next_own_pick": next_turn_pick,
                "opponent_rosters": opponents,
                "rounds": rounds,
                "team_count": team_count,
                "roster_slots": roster_slots,
                "categories": categories,
            }
            if drafting_slot == slot:
                if current_pick <= 1 and planned.index(overall) < preset_own_count:
                    continue
                own_pick_index = len(own_future_roster)
                if own_pick_index < len(availability_counters):
                    availability_counters[own_pick_index].update(item[1]["name"] for item in market_order)
                selected = _select_player(
                    market_order,
                    roster,
                    overall,
                    len(slot_future_picks),
                    punt_categories=own_punt_categories,
                    policy_mode=own_policy,
                    **select_kwargs,
                )
                own_future_roster.append(selected)
            else:
                # Opponents represent the draft market, not copies of our own
                # optimizer. This avoids validating the model against itself.
                missing = set(unfilled_roster_slots(roster, roster_slots))
                if missing and len(slot_future_picks) <= len(missing):
                    feasible = [
                        item for item in market_order
                        if any(can_play_slot(item[1], position) for position in missing)
                    ]
                    selected = (feasible or market_order)[0][1]
                else:
                    selected = market_order[0][1]
            roster.append(selected)
            remaining.pop(id(selected), None)

        if own_future_roster:
            first_pick_counter[own_future_roster[0]["name"]] += 1
        run_score = 0.0
        for index, player in enumerate(own_future_roster):
            roster_counter[player["name"]] += 1
            run_score += _player_value(player, own_punt_categories)
            if index < len(round_counters):
                round_counters[index][player["name"]] += 1
        total_score += run_score
        if evaluation_mode == "projected_volume":
            from .draft_evaluation import evaluate_projected_rosters
            league_result = evaluate_projected_rosters(team_rosters, slot, categories)
        else:
            league_result = _evaluate_rosters(team_rosters, slot, own_punt_categories)
        complete_roster = team_rosters[slot]
        gp_values = [float(player.get("games_played") or 0) for player in complete_roster]
        outcomes.append({
            **league_result,
            "score": run_score,
            "future_roster": own_future_roster,
            "average_games_played": sum(gp_values) / max(1, len(gp_values)),
            "low_gp_count": sum(value < 50 for value in gp_values),
        })

    denominator = max(1, runs)
    average_category_wins = sum(outcome["category_wins"] for outcome in outcomes) / denominator
    average_league_rank = sum(outcome["league_rank"] for outcome in outcomes) / denominator
    average_score = total_score / denominator
    top_four_strength_rate = round(sum(outcome["league_rank"] <= 4 for outcome in outcomes) / denominator * 100)
    top_n_strength_rate = round(sum(outcome["league_rank"] <= min(playoff_team_count, team_count) for outcome in outcomes) / denominator * 100)
    def representative_cost(outcome):
        relative_probabilities = [
            max(
                1 / max(1, max(round_counters[index].values(), default=1)),
                round_counters[index][player["name"]] / max(1, max(round_counters[index].values(), default=1)),
            )
            for index, player in enumerate(outcome["future_roster"])
            if index < len(round_counters)
        ]
        selection_rarity = sum(-math.log(probability) for probability in relative_probabilities)
        reach_cost = sum(
            max(0.0, (_market_position(player) or future_picks[index]) - future_picks[index] - 8) * 0.08
            for index, player in enumerate(outcome["future_roster"])
            if index < len(future_picks)
        )
        result_distance = (
            abs(outcome["league_rank"] - average_league_rank)
            + abs(outcome["category_wins"] - average_category_wins)
            + abs(outcome["score"] - average_score) / 10
        )
        return selection_rarity + reach_cost + result_distance * 0.05

    representative = min(outcomes, key=representative_cost)
    players_by_name = {player["name"]: player for player in usable}
    round_targets = []
    for index, counter in enumerate(round_counters):
        targets = []
        for name, count in counter.most_common(3):
            player = players_by_name[name]
            targets.append({
                "name": name,
                "position": player.get("position"),
                "espn_adp": player.get("espn_adp"),
                "espn_roto_rank": player.get("espn_roto_rank"),
                "espn_market_pick": player.get("espn_market_pick"),
                "games_played": player.get("games_played"),
                "selection_frequency": round(count / denominator * 100),
                "availability_frequency": round(availability_counters[index][name] / denominator * 100),
            })
        round_number = planned.index(future_picks[index]) + 1
        round_targets.append({"round": round_number, "pick": future_picks[index], "targets": targets})

    projected_roster = []
    for index, player in enumerate(representative["future_roster"]):
        if index >= len(future_picks):
            break
        next_turn_pick = _next_turn_pick(future_picks, index)
        market_pick = _market_position(player)
        adp_value, price_type, next_turn_availability = _draft_price(
            future_picks[index], market_pick, market_ceiling, next_turn_pick,
        )
        projected_roster.append({
            "round": planned.index(future_picks[index]) + 1,
            "pick": future_picks[index],
            "name": player["name"],
            "position": player.get("position"),
            "espn_adp": player.get("espn_adp"),
            "espn_roto_rank": player.get("espn_roto_rank"),
            "espn_market_pick": market_pick,
            "games_played": player.get("games_played"),
            "selection_frequency": round(round_counters[index][player["name"]] / denominator * 100),
            "availability_frequency": round(availability_counters[index][player["name"]] / denominator * 100),
            "adp_value": adp_value,
            "price_type": price_type,
            "next_turn_pick": next_turn_pick,
            "next_turn_availability": next_turn_availability,
        })

    result = {
        "slot": slot,
        "picks": planned,
        "average_score": round(average_score, 2),
        "average_category_wins": round(average_category_wins, 2),
        "average_league_rank": round(average_league_rank, 2),
        "top_four_strength_rate": top_four_strength_rate,
        "projected_top_n_strength_rate": top_n_strength_rate,
        # Backward-compatible aliases. These are roster-strength frequencies,
        # not calibrated season/playoff probabilities.
        "top_four_probability": top_four_strength_rate,
        "playoff_probability": top_n_strength_rate,
        "average_games_played": round(sum(outcome["average_games_played"] for outcome in outcomes) / denominator, 1),
        "average_low_gp_count": round(sum(outcome["low_gp_count"] for outcome in outcomes) / denominator, 1),
        "category_ranks": {
            category: round(sum(outcome["category_ranks"][category] for outcome in outcomes) / denominator, 1)
            for category in CATEGORIES
        },
        "category_margin": {
            category: round(sum(outcome["category_margin"][category] for outcome in outcomes) / denominator, 2)
            for category in CATEGORIES
        },
        "first_targets": [
            {"name": name, "frequency": round(count / denominator * 100)}
            for name, count in first_pick_counter.most_common(3)
        ],
        "core_targets": [
            {"name": name, "frequency": round(count / denominator * 100)}
            for name, count in roster_counter.most_common(6)
        ],
        "round_targets": round_targets,
        "projected_roster": projected_roster,
    }
    if include_samples:
        result["category_win_samples"] = [round(outcome["category_wins"], 6) for outcome in outcomes]
        result["league_rank_samples"] = [outcome["league_rank"] for outcome in outcomes]
    return result


def simulate_draft_market(
    players,
    team_count,
    pick_order=(),
    team_id=None,
    current_pick=1,
    rounds=14,
    selected_slot=None,
    existing_rosters_by_slot=None,
    own_existing_roster=None,
    playoff_team_count=8,
    own_punt_categories=(),
    roster_slots=None,
    own_policy="adaptive",
):
    """Model every possible slot or the known live snake slot."""
    team_count = max(1, int(team_count or 1))
    if pick_order and team_id in pick_order:
        slot = list(pick_order).index(team_id) + 1
        runs = 80 if own_policy == "adaptive" else 240
        result = _simulate_slot(
            players, slot, team_count, rounds, runs, current_pick, 9100 + current_pick,
            existing_rosters_by_slot, own_existing_roster, playoff_team_count,
            own_punt_categories, roster_slots, own_policy=own_policy,
        )
        future = [pick for pick in result.get("picks", []) if pick >= current_pick]
        return {
            "mode": "known_order",
            "runs": runs,
            "slot": slot,
            "next_pick": future[0] if future else None,
            "following_pick": future[1] if len(future) > 1 else None,
            "slot_result": result,
        }

    if selected_slot is not None:
        slot = max(1, min(team_count, int(selected_slot)))
        runs = 240
        result = _simulate_slot(
            players, slot, team_count, rounds, runs, 1, 12000 + slot,
            existing_rosters_by_slot, own_existing_roster, playoff_team_count,
            own_punt_categories, roster_slots, own_policy=own_policy,
        )
        return {
            "mode": "selected_slot",
            "runs": runs,
            "slot": slot,
            "next_pick": result.get("picks", [None])[0],
            "following_pick": result.get("picks", [None, None])[1],
            "slot_result": result,
        }

    runs_per_slot = 12 if own_policy == "adaptive" else 24
    slots = [
        _simulate_slot(
            players, slot, team_count, rounds, runs_per_slot, 1, 7000 + slot,
            existing_rosters_by_slot, own_existing_roster, playoff_team_count,
            own_punt_categories, roster_slots, own_policy=own_policy,
        )
        for slot in range(1, team_count + 1)
    ]
    ranked = sorted(slots, key=lambda item: (item["average_category_wins"], -item["average_league_rank"]), reverse=True)
    return {
        "mode": "all_slots",
        "runs": runs_per_slot * team_count,
        "runs_per_slot": runs_per_slot,
        "slots_analyzed": team_count,
        "best_slots": [result["slot"] for result in ranked[:3]],
        "slot_results": slots,
    }
