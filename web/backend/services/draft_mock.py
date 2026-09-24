"""Single-run snake mock: a human slot against a model field."""

from __future__ import annotations

from copy import deepcopy
import random

from core.config import CATEGORIES

from .draft_benchmark import (
    _feasible_pool,
    _identity,
    _population_profiles,
    _rank_value,
    _scenario,
    _select_player,
)
from .draft_evaluation import evaluate_projected_rosters
from .draft_simulation import _next_turn_pick, _slot_at_pick, snake_pick_numbers


POLICY_MODES = {
    "model": "legacy",
    "adaptive": "adaptive",
    "adaptive_heuristic": "adaptive_heuristic",
    "v8": "v8",
}

POLICY_LABELS = {
    "human": "Вы",
    "roto": "ESPN ROTO",
    "adp": "ADP",
    "model": "Модель",
    "adaptive": "Адаптив",
    "adaptive_heuristic": "Эвристика",
    "v8": "Нейросеть V8",
}

STRONG_PROFILE = {"policy": "adaptive", "punts": ()}
V8_PROFILE = {"policy": "v8", "punts": ()}
ADVISOR_MODES = ("heuristic", "v8")


def _strong_profiles(team_count, seed=9105, human_slot=None):
    """Most strong opponents stay adaptive; a seeded sample uses V8."""
    profiles = {slot: dict(STRONG_PROFILE) for slot in range(1, team_count + 1)}
    opponents = [slot for slot in range(1, team_count + 1) if slot != human_slot]
    if len(opponents) < 7:
        return profiles
    count = max(1, len(opponents) // 3)
    rng = random.Random(f"v8-field:{int(seed)}:{team_count}:{human_slot}")
    for slot in rng.sample(opponents, count):
        profiles[slot] = dict(V8_PROFILE)
    return profiles


class MockDraftError(ValueError):
    """Invalid human pick against the current mock board."""


def _public_player(player, punt_categories=()):
    z_scores = player.get("z_scores") or {}
    punts = set(punt_categories or ())
    if z_scores:
        total_z = sum(
            float(value or 0)
            for category, value in z_scores.items()
            if category not in punts
        )
        general_z = sum(float(value or 0) for value in z_scores.values())
    else:
        total_z = float(player.get("total_z") or player.get("general_z") or 0)
        general_z = float(player.get("general_z") or total_z)
    return {
        "player_id": player.get("player_id"),
        "name": player.get("name"),
        "position": player.get("position"),
        "nba_team": player.get("nba_team"),
        "eligible_slots": list(player.get("eligible_slots") or ()),
        "total_z": round(total_z, 3),
        "general_z": round(general_z, 3),
        "z_scores": z_scores,
        "espn_market_pick": player.get("espn_market_pick"),
        "games_played": player.get("games_played"),
        "stats": player.get("stats") or {},
        "analysis_context": "draft",
    }


def _policy_label(profile):
    policy = profile.get("policy")
    label = POLICY_LABELS.get(policy, policy)
    punts = tuple(profile.get("punts") or ())
    if punts and policy != "human":
        return f"{label} · punt {' + '.join(punts)}"
    return label


def _advisor_label(mode, punt_categories=()):
    base = "Нейросеть V8" if mode == "v8" else "Эвристика"
    punts = tuple(punt_categories or ())
    if punts and mode != "v8":
        return f"{base} · punt {' + '.join(punts)}"
    return base


def _advisor_profile(advisor, punt_categories=()):
    mode = advisor if advisor in ADVISOR_MODES else "heuristic"
    if mode == "v8":
        return dict(V8_PROFILE), mode
    return {"policy": "adaptive", "punts": tuple(punt_categories or ())}, mode


def _opponent_profiles(team_count, categories, opponent_field, seed=9105, human_slot=None):
    if opponent_field == "strong":
        return _strong_profiles(team_count, seed=seed, human_slot=human_slot)
    return _population_profiles(team_count, categories, opponent_field)


def _choose_opponent(remaining, drafting_slot, overall, rosters, profile, market, opponent_rank,
                     team_count, rounds, roster_slots, categories):
    if profile.get("policy") in POLICY_MODES:
        slot_picks = [
            pick for pick in snake_pick_numbers(drafting_slot, team_count, rounds)
            if pick >= overall
        ]
        market_order = sorted(
            ([market[identity], player] for identity, player in remaining.items()),
            key=lambda item: item[0],
        )
        return _select_player(
            market_order,
            rosters[drafting_slot],
            overall,
            len(slot_picks),
            next_own_pick=_next_turn_pick(slot_picks, 0),
            punt_categories=tuple(profile.get("punts") or ()),
            opponent_rosters=[rosters[slot] for slot in rosters if slot != drafting_slot],
            rounds=rounds,
            team_count=team_count,
            roster_slots=roster_slots,
            categories=categories,
            policy_mode=POLICY_MODES[profile["policy"]],
        )
    candidates = _feasible_pool(
        remaining.values(),
        rosters[drafting_slot],
        rounds - len(rosters[drafting_slot]),
        roster_slots,
    )
    rank_field = "espn_adp" if profile.get("policy") == "adp" else "espn_roto_rank"
    return min(
        candidates,
        key=lambda player: (
            _rank_value(player, rank_field),
            opponent_rank[_identity(player)],
        ),
    )


def _h2h_sort_key(row):
    return (
        -(row["matchup_wins"] + 0.5 * row["matchup_ties"]),
        -row["category_wins"],
        row["slot"],
    )


def _league_table(rosters, profiles, human_slot, slot_names, categories):
    standings = []
    for slot, roster in rosters.items():
        result = evaluate_projected_rosters(rosters, slot, categories)
        standings.append({
            "slot": slot,
            "team_name": slot_names.get(slot) or f"Слот {slot}",
            "is_you": slot == human_slot,
            "policy": profiles[slot]["policy"],
            "policy_label": _policy_label(profiles[slot]),
            "punt_categories": list(profiles[slot].get("punts") or ()),
            "category_wins": round(result["category_wins"], 3),
            "matchup_wins": int(result["matchup_wins"]),
            "matchup_ties": int(result["matchup_ties"]),
            "matchup_losses": int(result["matchup_losses"]),
            "league_rank": result["league_rank"],
            "category_ranks": result["category_ranks"],
            "category_totals": result["category_totals"],
            "roster": [_public_player(player) for player in roster],
        })
    standings.sort(key=_h2h_sort_key)
    rank = 1
    previous = None
    for index, row in enumerate(standings):
        key = _h2h_sort_key(row)[:2]
        if previous is not None and key != previous:
            rank = index + 1
        row["league_rank"] = rank
        previous = key
    return standings


def _team_rows(rosters, profiles, human_slot, slot_names, team_count):
    return [
        {
            "slot": team_slot,
            "team_name": slot_names.get(team_slot) or f"Слот {team_slot}",
            "is_you": team_slot == human_slot,
            "policy": profiles[team_slot]["policy"],
            "policy_label": _policy_label(profiles[team_slot]),
            "punt_categories": list(profiles[team_slot].get("punts") or ()),
            "roster": [_public_player(player) for player in rosters[team_slot]],
        }
        for team_slot in range(1, team_count + 1)
    ]


def play_mock_draft(
    players,
    *,
    slot,
    team_count,
    rounds,
    human_picks,
    seed=9105,
    roster_slots=None,
    categories=None,
    opponent_field="mixed",
    slot_names=None,
    advisor="heuristic",
    punt_categories=(),
):
    """Replay a snake draft, pausing when the human slot is on the clock."""
    categories = list(categories or CATEGORIES)
    team_count = max(1, int(team_count))
    rounds = max(1, int(rounds))
    slot = max(1, min(team_count, int(slot)))
    names = slot_names or {}
    usable = [player for player in players if _identity(player) is not None]
    if len(usable) < team_count:
        raise MockDraftError("Недостаточно игроков для мок-драфта")

    profiles = _opponent_profiles(
        team_count, categories, opponent_field, seed=seed, human_slot=slot,
    )
    profiles[slot] = {"policy": "human", "punts": ()}
    market, opponent_rank = _scenario(usable, seed, 0)
    remaining = {_identity(player): deepcopy(player) for player in usable}
    by_id = {}
    for player in remaining.values():
        player_id = player.get("player_id")
        if player_id is not None:
            by_id[int(player_id)] = _identity(player)
    rosters = {team_slot: [] for team_slot in range(1, team_count + 1)}
    pick_log = []
    round_reports = []
    queued = [int(player_id) for player_id in human_picks]
    planned = snake_pick_numbers(slot, team_count, rounds)
    total_picks = team_count * rounds
    advisor_profile, advisor_mode = _advisor_profile(advisor, punt_categories)
    advisor_punts = list(advisor_profile.get("punts") or ())

    def payload(status, overall, extra=None):
        completed = round_reports[-1]["standings"] if round_reports else None
        body = {
            "status": status,
            "slot": slot,
            "overall": overall,
            "round": (overall - 1) // team_count + 1 if overall else 1,
            "round_pick": (overall - 1) % team_count + 1 if overall else 1,
            "your_pick_index": len(rosters[slot]),
            "your_picks_left": rounds - len(rosters[slot]),
            "planned_picks": planned,
            "seed": seed,
            "opponent_field": opponent_field,
            "advisor": advisor_mode,
            "advisor_label": _advisor_label(advisor_mode, advisor_punts),
            "punt_categories": advisor_punts,
            "categories": categories,
            "team_count": team_count,
            "rounds": rounds,
            "teams": _team_rows(rosters, profiles, slot, names, team_count),
            "pick_log": pick_log,
            "your_roster": [_public_player(player, advisor_punts) for player in rosters[slot]],
            "round_reports": round_reports,
            "standings": completed,
        }
        if extra:
            body.update(extra)
        return body

    for overall in range(1, total_picks + 1):
        if not remaining:
            break
        drafting_slot = _slot_at_pick(overall, team_count)
        if drafting_slot == slot:
            if not queued:
                available = sorted(
                    remaining.values(),
                    key=lambda player: (
                        float(player.get("espn_market_pick") or _rank_value(player, "espn_roto_rank")),
                        -float(player.get("total_z") or player.get("general_z") or 0),
                        str(player.get("name") or ""),
                    ),
                )
                model_player = _choose_opponent(
                    remaining, slot, overall, rosters, advisor_profile,
                    market, opponent_rank, team_count, rounds, roster_slots, categories,
                ) if remaining else None
                return payload("on_the_clock", overall, {
                    "picks_until_turn": 0,
                    "available": [_public_player(player, advisor_punts) for player in available],
                    "model_pick": _public_player(model_player, advisor_punts) if model_player else None,
                })
            player_id = queued.pop(0)
            identity = by_id.get(player_id)
            selected = remaining.get(identity) if identity is not None else None
            if selected is None:
                raise MockDraftError(f"Игрок {player_id} недоступен")
        else:
            selected = _choose_opponent(
                remaining, drafting_slot, overall, rosters, profiles[drafting_slot],
                market, opponent_rank, team_count, rounds, roster_slots, categories,
            )
        rosters[drafting_slot].append(selected)
        remaining.pop(_identity(selected), None)
        pick_log.append({
            "overall": overall,
            "round": (overall - 1) // team_count + 1,
            "slot": drafting_slot,
            "is_you": drafting_slot == slot,
            "team_name": names.get(drafting_slot) or f"Слот {drafting_slot}",
            "policy_label": _policy_label(profiles[drafting_slot]),
            "player": _public_player(selected),
        })
        if overall % team_count == 0:
            round_reports.append({
                "round": overall // team_count,
                "standings": _league_table(rosters, profiles, slot, names, categories),
            })

    if queued:
        raise MockDraftError("Лишние пики после конца драфта")

    standings = _league_table(rosters, profiles, slot, names, categories)
    you = next(row for row in standings if row["is_you"])
    result = payload("complete", total_picks, {
        "picks_until_turn": None,
        "available": [],
        "model_pick": None,
        "standings": standings,
        "category_wins": you["category_wins"],
        "league_rank": you["league_rank"],
        "category_ranks": you["category_ranks"],
        "category_totals": you["category_totals"],
    })
    return result
