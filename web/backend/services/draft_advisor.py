"""Punt-aware live draft advice: who to take now so the final roster wins categories."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math

from core.config import CATEGORIES

from .draft_simulation import (
    POSITIONS,
    _evaluate_rosters,
    _market_position,
    _player_value,
    _simulate_slot,
    conditional_availability,
)


TAKE_NOW_ACTIONS = {"брать сейчас", "риск ожидания", "оценить сейчас"}
WAIT_ACTIONS = {"можно ждать"}
FALL_ACTIONS = {"нужен фолл"}


def _active_categories(punt_categories=()):
    active = [category for category in CATEGORIES if category not in punt_categories]
    return active or list(CATEGORIES)


def _sigmoid(margin, scale=1.8):
    return 1.0 / (1.0 + math.exp(-margin / scale))


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def draft_phase(roster_size, rounds):
    rounds = max(1, int(rounds or 1))
    filled = roster_size / rounds
    if roster_size < 2 or filled < 0.22:
        return "early"
    if filled < 0.72:
        return "mid"
    return "late"


def leverage_weight(phase, roster_size):
    if roster_size < 1:
        return 0.08
    if phase == "early":
        return 0.22
    if phase == "mid":
        return 0.72
    return 1.15


def category_totals(roster, punt_categories=()):
    totals = {category: 0.0 for category in _active_categories(punt_categories)}
    for player in roster or ():
        z_scores = player.get("z_scores") or {}
        for category in totals:
            totals[category] += float(z_scores.get(category, 0) or 0)
    return totals


def opponent_medians(opponent_rosters, punt_categories=()):
    active = _active_categories(punt_categories)
    if not opponent_rosters:
        return {category: 0.0 for category in active}
    values = {category: [] for category in active}
    for roster in opponent_rosters:
        totals = category_totals(roster, punt_categories)
        for category in active:
            values[category].append(totals[category])
    return {category: _median(values[category]) for category in active}


def league_medians_from_slots(team_rosters, own_slot, punt_categories=()):
    opponents = [
        roster for slot, roster in (team_rosters or {}).items()
        if slot != own_slot
    ]
    return opponent_medians(opponents, punt_categories)


def _durability_penalty(player):
    injury = str(player.get("injury_status") or "ACTIVE").upper()
    if injury in {"OUT", "INJURY_RESERVE", "IR"}:
        injury_penalty = 2.4
    elif injury in {"DAY_TO_DAY", "DTD", "QUESTIONABLE", "DOUBTFUL"}:
        injury_penalty = 0.45
    else:
        injury_penalty = 0.0
    games_played = player.get("games_played")
    if games_played is None:
        return injury_penalty
    games_played = float(games_played)
    if games_played <= 0:
        return injury_penalty + 0.55
    if games_played >= 50:
        return injury_penalty
    return injury_penalty + min(1.7, (50.0 - games_played) * 0.035)


def _position_adjustment(position, position_counts, missing_positions, own_picks_left, phase):
    depth = position_counts[position]
    stack_penalty = max(0, depth - 1) * 1.75 + max(0, depth - 3) * 4.0
    if phase == "early":
        stack_penalty *= 0.45
    elif phase == "late":
        stack_penalty *= 1.25
    fill_bonus = 0.0
    if position in missing_positions:
        fill_bonus = 1.25 if phase != "early" else 0.55
        if own_picks_left <= len(missing_positions):
            fill_bonus += 2.8
    return fill_bonus - stack_penalty


def _category_scarcity(player, elite_remaining, team_count, punt_categories=()):
    z_scores = player.get("z_scores") or {}
    if not elite_remaining:
        return 0.0
    bonus = 0.0
    for category, remaining in elite_remaining.items():
        if category in punt_categories:
            continue
        if z_scores.get(category, 0) < 0.55:
            continue
        shortage = max(0.0, 1.0 - remaining / max(1.0, team_count * 1.15))
        bonus += shortage * min(1.8, z_scores[category]) * 0.55
    return bonus


def _win_probability_delta(own_total, median, added_z):
    before = _sigmoid(own_total - median)
    after = _sigmoid(own_total + added_z - median)
    return after - before, before, after


def _leverage(player, own_totals, medians, weight, punt_categories=()):
    z_scores = player.get("z_scores") or {}
    if not z_scores or weight <= 0:
        return 0.0, []
    score = 0.0
    flips = []
    for category, own_total in own_totals.items():
        if category in punt_categories:
            continue
        added = float(z_scores.get(category, 0) or 0)
        if added == 0:
            continue
        delta, before, after = _win_probability_delta(own_total, medians.get(category, 0.0), added)
        score += delta * 6.4
        if before < 0.5 <= after and added > 0:
            flips.append(category)
            score += 0.85
    return score * weight, flips


def expected_replacement_value(players, eval_pick, next_own_pick, punt_categories=()):
    values = []
    for player in players:
        market = _market_position(player)
        value = _player_value(player, punt_categories)
        if next_own_pick is None:
            values.append(value)
            continue
        survival = conditional_availability(market, next_own_pick, eval_pick)
        if survival is None or survival >= 38:
            values.append(value)
    if not values:
        return 0.0
    values.sort(reverse=True)
    index = min(len(values) - 1, 2 if next_own_pick else 1)
    return values[index]


def elite_remaining_counts(players, punt_categories=(), threshold=0.75):
    counts = Counter()
    for player in players:
        z_scores = player.get("z_scores") or {}
        for category, value in z_scores.items():
            if category not in punt_categories and value >= threshold:
                counts[category] += 1
    return dict(counts)


@dataclass
class ScoringContext:
    eval_pick: int
    next_own_pick: int | None
    is_on_the_clock: bool
    picks_until_turn: int | None
    own_picks_left: int
    roster: list = field(default_factory=list)
    remaining: list = field(default_factory=list)
    punt_categories: tuple = ()
    team_count: int = 10
    rounds: int = 14
    phase: str = "early"
    own_totals: dict = field(default_factory=dict)
    medians: dict = field(default_factory=dict)
    position_counts: Counter = field(default_factory=Counter)
    missing_positions: set = field(default_factory=set)
    replacement_at_next: float = 0.0
    elite_remaining: dict = field(default_factory=dict)
    replacement_by_position: dict = field(default_factory=dict)


def build_scoring_context(
    *,
    roster,
    remaining,
    eval_pick,
    next_own_pick=None,
    is_on_the_clock=True,
    picks_until_turn=0,
    own_picks_left=8,
    punt_categories=(),
    team_count=10,
    rounds=14,
    opponent_rosters=(),
    opponent_medians_map=None,
):
    punt_categories = tuple(punt_categories or ())
    phase = draft_phase(len(roster or ()), rounds)
    own_totals = category_totals(roster, punt_categories)
    medians = opponent_medians_map if opponent_medians_map is not None else opponent_medians(
        opponent_rosters, punt_categories,
    )
    position_counts = Counter(player.get("position") for player in roster or ())
    missing_positions = {position for position in POSITIONS if position_counts[position] == 0}
    replacement_values = {}
    by_position = defaultdict(list)
    for player in remaining or ():
        by_position[player.get("position")].append(_player_value(player, punt_categories))
    for position, values in by_position.items():
        values.sort(reverse=True)
        replacement_index = min(len(values) - 1, max(0, team_count * 2 - 1))
        replacement_values[position] = values[replacement_index]
    return ScoringContext(
        eval_pick=max(1, int(eval_pick or 1)),
        next_own_pick=next_own_pick,
        is_on_the_clock=bool(is_on_the_clock),
        picks_until_turn=picks_until_turn,
        own_picks_left=max(1, int(own_picks_left or 1)),
        roster=list(roster or ()),
        remaining=list(remaining or ()),
        punt_categories=punt_categories,
        team_count=max(1, int(team_count or 1)),
        rounds=max(1, int(rounds or 1)),
        phase=phase,
        own_totals=own_totals,
        medians=medians,
        position_counts=position_counts,
        missing_positions=missing_positions,
        replacement_at_next=expected_replacement_value(
            remaining, eval_pick, next_own_pick, punt_categories,
        ),
        elite_remaining=elite_remaining_counts(remaining, punt_categories),
        replacement_by_position=replacement_values,
    )


def score_draft_pick(player, context: ScoringContext, market_pick=None):
    """Return a decision score for taking this player at context.eval_pick."""
    punt_categories = context.punt_categories
    base_value = _player_value(player, punt_categories)
    z_scores = player.get("z_scores") or {}
    position = player.get("position")
    sampled_market = float(market_pick) if market_pick is not None else None
    listed_market = _market_position(player)
    market = sampled_market if sampled_market is not None else listed_market
    if market is None:
        market = float(context.eval_pick)

    reach = max(0.0, market - context.eval_pick)
    listed_reach = max(0.0, (listed_market or market) - context.eval_pick)
    can_wait = context.next_own_pick is not None and market >= context.next_own_pick
    listed_can_wait = context.next_own_pick is not None and (listed_market or market) >= context.next_own_pick
    next_survival = conditional_availability(listed_market or market, context.next_own_pick, context.eval_pick)
    next_survival_rate = None if next_survival is None else next_survival / 100.0

    leverage, flips = _leverage(
        player, context.own_totals, context.medians, leverage_weight(context.phase, len(context.roster)),
        punt_categories,
    )
    vorp = base_value - context.replacement_by_position.get(position, context.replacement_at_next)
    scarcity = max(vorp, 0.0) * (0.22 if context.phase == "early" else 0.18)
    scarcity += _category_scarcity(player, context.elite_remaining, context.team_count, punt_categories)
    position_term = _position_adjustment(
        position, context.position_counts, context.missing_positions, context.own_picks_left, context.phase,
    )
    durability = _durability_penalty(player)

    surplus = base_value - context.replacement_at_next
    wait_penalty = 0.0
    urgency = 0.0
    reach_penalty = 0.0
    if context.is_on_the_clock:
        if can_wait:
            wait_penalty += 4.0
        if listed_can_wait:
            wait_penalty += 2.0
        if next_survival_rate is not None:
            if next_survival_rate >= 0.70:
                wait_penalty += max(0.0, surplus) * 0.55
            elif next_survival_rate >= 0.35:
                wait_penalty += max(0.0, surplus) * 0.18
            else:
                urgency = max(0.0, surplus) * (1.0 - next_survival_rate) * 0.62
        reach_penalty = reach * 0.25 + listed_reach * 0.12
        if reach >= 12 and (next_survival_rate or 0) >= 0.45:
            reach_penalty += 1.6

    availability_weight = 1.0
    availability = player.get("availability_probability")
    if not context.is_on_the_clock and availability is not None:
        availability_weight = 0.10 + 0.90 * (availability / 100.0)

    raw = (
        base_value
        + leverage
        + scarcity
        + position_term
        + urgency
        - wait_penalty
        - reach_penalty
        - durability
    )
    score = raw * availability_weight

    reasons = []
    helpful = [
        category for category, value in sorted(z_scores.items(), key=lambda item: item[1], reverse=True)
        if category not in punt_categories and value > 0.45
    ]
    if flips:
        reasons.append(f"переводит {', '.join(flips[:2])}")
    elif helpful:
        reasons.append(f"усиливает {', '.join(helpful[:2])}")
    if position_term >= 1.2:
        reasons.append(f"закрывает {position}")
    if urgency >= 0.8:
        reasons.append("не доживёт до следующего хода")
    elif can_wait or listed_can_wait:
        reasons.append("можно взять позже")
    if punt_categories and base_value >= 1.5:
        reasons.append(f"фит к punt {', '.join(punt_categories[:2])}")
    if durability >= 1.0:
        reasons.append("риск по здоровью / GP")
    if not reasons:
        reasons.append("лучшая доступная ценность стратегии")

    return {
        "score": score,
        "raw_score": raw,
        "base_value": base_value,
        "leverage": leverage,
        "scarcity": scarcity,
        "position_term": position_term,
        "urgency": urgency,
        "wait_penalty": wait_penalty,
        "reach_penalty": reach_penalty,
        "durability_penalty": durability,
        "availability_weight": availability_weight,
        "flips": flips,
        "reasons": reasons,
        "vorp": vorp,
    }


def apply_pick_scores(players, context: ScoringContext):
    for player in players:
        breakdown = score_draft_pick(player, context)
        player["score"] = round(breakdown["score"], 3)
        player["need_bonus"] = round(breakdown["leverage"] + breakdown["position_term"], 3)
        player["scarcity_bonus"] = round(breakdown["scarcity"], 3)
        player["vorp"] = round(breakdown["vorp"], 3)
        player["score_breakdown"] = {
            key: round(breakdown[key], 3) if isinstance(breakdown[key], float) else breakdown[key]
            for key in (
                "raw_score", "base_value", "leverage", "scarcity", "position_term",
                "urgency", "wait_penalty", "reach_penalty", "durability_penalty",
                "availability_weight", "flips",
            )
        }
        player["reason"] = "; ".join(breakdown["reasons"])
    players.sort(key=lambda player: player.get("score", 0), reverse=True)
    return players


def _lane_for(player, is_on_the_clock):
    action = player.get("draft_action")
    availability = player.get("availability_probability")
    next_probability = player.get("next_round_probability")
    if is_on_the_clock:
        if action in TAKE_NOW_ACTIONS or (next_probability is not None and next_probability < 35):
            return "take_now"
        if action in WAIT_ACTIONS or (next_probability is not None and next_probability >= 70):
            return "wait"
        return "fallback"
    if action in FALL_ACTIONS or (availability is not None and availability < 35):
        return "reach"
    if availability is not None and availability >= 70:
        return "target"
    return "bubble"


def build_pick_advice(players, context: ScoringContext, limit=6):
    if not players:
        return {
            "primary": None,
            "take_now": [],
            "wait": [],
            "fallback": [],
            "lanes": {},
            "phase": context.phase,
            "is_on_the_clock": context.is_on_the_clock,
            "summary": "Нет доступных игроков для рекомендации.",
        }

    grouped = {"take_now": [], "wait": [], "fallback": []}
    for player in players:
        lane = _lane_for(player, context.is_on_the_clock)
        player["advice_lane"] = lane
        if lane == "take_now":
            grouped["take_now"].append(player)
        elif lane in {"wait", "target"}:
            grouped["wait"].append(player)
        else:
            grouped["fallback"].append(player)

    primary = players[0]
    if context.is_on_the_clock and grouped["take_now"]:
        best_urgent = grouped["take_now"][0]
        if best_urgent["score"] >= primary["score"] - 1.35:
            primary = best_urgent

    def slim(player):
        return {
            "player_id": player.get("player_id"),
            "name": player.get("name"),
            "position": player.get("position"),
            "nba_team": player.get("nba_team"),
            "score": player.get("score"),
            "total_z": player.get("total_z"),
            "reason": player.get("reason"),
            "draft_action": player.get("draft_action"),
            "availability_probability": player.get("availability_probability"),
            "next_round_probability": player.get("next_round_probability"),
            "advice_lane": player.get("advice_lane"),
            "espn_market_pick": player.get("espn_market_pick"),
            "espn_adp": player.get("espn_adp"),
            "games_played": player.get("games_played"),
            "z_scores": player.get("z_scores"),
            "lookahead_wins": player.get("lookahead_wins"),
            "injury_status": player.get("injury_status"),
        }

    take_now = [slim(player) for player in grouped["take_now"][:4]]
    wait = [slim(player) for player in grouped["wait"][:3]]
    fallback = [slim(player) for player in grouped["fallback"][:3]]
    seen = {primary.get("player_id") or primary.get("name")}
    extras = []
    for group in (take_now, wait, fallback):
        for player in group:
            identity = player.get("player_id") or player.get("name")
            if identity in seen:
                continue
            seen.add(identity)
            extras.append(player)
            if len(extras) >= max(0, limit - 1):
                break
        if len(extras) >= max(0, limit - 1):
            break

    if context.is_on_the_clock:
        if primary.get("advice_lane") == "wait":
            summary = f"Лучший по ценности — {primary['name']}, но его можно подождать."
        else:
            summary = f"Сейчас брать {primary['name']}: {primary.get('reason') or 'максимум EV состава'}."
    elif context.picks_until_turn:
        summary = (
            f"До вашего пика {context.picks_until_turn} выборов. "
            f"Главная цель — {primary['name']}."
        )
    else:
        summary = f"Рекомендация стратегии: {primary['name']}."

    return {
        "primary": slim(primary),
        "take_now": take_now,
        "wait": wait,
        "fallback": fallback,
        "board": [slim(primary), *extras],
        "phase": context.phase,
        "is_on_the_clock": context.is_on_the_clock,
        "picks_until_turn": context.picks_until_turn,
        "summary": summary,
        "method": "punt_aware_ev_lookahead",
    }


def _candidate_profile(player):
    return {
        "name": player["name"],
        "position": player.get("position"),
        "z_scores": player.get("z_scores") or {},
        "general_z": player.get("general_z", player.get("total_z", 0)),
        "score": player.get("total_z", player.get("score", 0)),
        "games_played": player.get("games_played", 0),
        "injury_status": player.get("injury_status"),
        "espn_adp": player.get("espn_adp"),
        "espn_market_pick": player.get("espn_market_pick"),
        "espn_roto_rank": player.get("espn_roto_rank"),
    }


def lookahead_rerank(
    players,
    *,
    existing_rosters_by_slot,
    slot,
    team_count,
    rounds,
    current_pick,
    punt_categories=(),
    playoff_team_count=8,
    candidate_count=8,
    runs=8,
):
    """Re-rank on-the-clock options by expected remaining category wins."""
    if not players or not slot or not existing_rosters_by_slot:
        return players
    candidates = [player for player in players[: max(4, candidate_count)] if player.get("name")]
    if len(candidates) < 2:
        return players

    results = []
    for index, candidate in enumerate(candidates):
        remaining = [player for player in players if player.get("name") != candidate["name"]]
        if not remaining:
            continue
        rosters = {
            team_slot: list(roster)
            for team_slot, roster in existing_rosters_by_slot.items()
        }
        rosters.setdefault(slot, [])
        rosters[slot] = list(rosters[slot]) + [_candidate_profile(candidate)]
        try:
            simulation = _simulate_slot(
                remaining,
                slot,
                team_count,
                rounds,
                runs,
                current_pick + 1,
                9400 + current_pick * 17 + index,
                rosters,
                None,
                playoff_team_count,
                punt_categories,
            )
        except Exception:
            continue
        wins = float(simulation.get("average_category_wins") or 0)
        rank = float(simulation.get("average_league_rank") or team_count)
        ev = wins * 2.2 - rank * 0.12
        candidate["lookahead_wins"] = round(wins, 3)
        candidate["lookahead_rank"] = round(rank, 2)
        candidate["lookahead_ev"] = round(ev, 3)
        results.append((ev, candidate["score"], candidate))

    if not results:
        return players

    ev_values = [item[0] for item in results]
    score_values = [item[1] for item in results]
    ev_span = max(ev_values) - min(ev_values) or 1.0
    score_span = max(score_values) - min(score_values) or 1.0
    blended = []
    for ev, fast_score, candidate in results:
        ev_norm = (ev - min(ev_values)) / ev_span
        score_norm = (fast_score - min(score_values)) / score_span
        blended_score = 0.62 * ev_norm + 0.38 * score_norm
        candidate["score"] = round(candidate["score"] + blended_score * 1.8, 3)
        candidate["score_breakdown"] = {
            **(candidate.get("score_breakdown") or {}),
            "lookahead_ev": round(ev, 3),
            "lookahead_wins": candidate.get("lookahead_wins"),
        }
        if candidate.get("lookahead_wins") is not None:
            suffix = f"EV {candidate['lookahead_wins']:.2f} кат./матчап"
            if suffix not in (candidate.get("reason") or ""):
                candidate["reason"] = f"{candidate.get('reason')}; {suffix}" if candidate.get("reason") else suffix
        blended.append((blended_score, candidate))

    ranked_names = {candidate["name"] for _, candidate in blended}
    head = [candidate for _, candidate in sorted(blended, key=lambda item: item[0], reverse=True)]
    tail = [player for player in players if player.get("name") not in ranked_names]
    return head + tail
