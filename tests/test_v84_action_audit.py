from scripts.draft_v84_action_audit import summarize
from scripts.draft_v84_opponent_robustness import choose_roto


def test_action_summary_keeps_h2h_separate_from_composite_utility():
    rows = [
        {"format_id": "main-c11-t14-r13", "baseline": "A", "selected": "B",
         "independent_delta": 0.02, "independent_h2h_delta": -0.01},
        {"format_id": "s8-t10-r13", "baseline": "C", "selected": "C",
         "independent_delta": 0.01, "independent_h2h_delta": 0.0},
    ]

    summary = summarize(rows)

    assert summary["mean_independent_delta"] > 0
    assert summary["mean_independent_h2h_delta"] < 0
    assert summary["h2h_by_format"]["main-c11-t14-r13"] == -0.01
    assert summary["h2h_by_format"]["s8-t10-r13"] == 0.0


def test_roto_transfer_uses_active_league_categories():
    class State:
        categories = ("FG%", "DD")
        players = [
            {"z_scores": {"FG%": 2.0, "DD": 0.0, "3PM": -10.0}},
            {"z_scores": {"FG%": 0.0, "DD": 1.0, "3PM": 100.0}},
        ]

        def legal(self):
            return [0, 1]

    assert choose_roto(State(), [0.0, 0.0]) == 0
