import numpy as np

from scripts import draft_v826_adaptive_labels as v826


def test_contender_screen_keeps_no_punt_and_minimum_candidates():
    settings, _, _ = v826.configuration()
    values = np.asarray([[.10] * 16, [.11] * 16, [.08] * 16, [.07] * 16, [.06] * 16])
    selected = v826.select_contenders(values, no_punt=0, settings=settings)
    assert 0 in selected
    assert len(selected) >= settings["minimum_contenders"]


def test_confirmation_trigger_includes_unresolved_and_high_regret():
    settings, _, _ = v826.configuration()
    base = {"best_vs_no_punt_resolved": True, "full_top_second_gap": .02,
            "cross_selected_positive": [True, True], "cross_regrets": [0, 0]}
    assert not v826.needs_confirmation(base, settings)
    assert v826.needs_confirmation({**base, "best_vs_no_punt_resolved": False}, settings)
    assert v826.needs_confirmation({**base, "cross_regrets": [0, .02]}, settings)
