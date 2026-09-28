import json

from scripts.draft_v84_seat5_confirmation import CONFIG, summary
from scripts.draft_v84_robust_pilot import jobs_for


def test_confirmation_is_fresh_and_only_targets_seat_five():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    jobs = jobs_for(config)
    assert len(jobs) == 24
    assert {job[1] for job in jobs} == {5}
    assert {job[2] for job in jobs} == {0, 3, 7}
    assert config["seed"] != 840926


def test_seat_five_requires_positive_interval_and_both_opponent_fields():
    rows = []
    for completed in (0, 3, 7):
        for replicate in range(8):
            rows.append({"format_id": "main-c11-t14-r13", "seat": 5,
                         "completed_hero_picks": completed, "replicate": replicate,
                         "baseline": "A", "selected": "A", "independent_h2h_delta": 0.0,
                         "independent_h2h_delta_samples": {"heuristic": [0.0], "roto": [0.0]}})
    assert summary(rows)["decision"] == "IMPROVE_TEACHER_BEFORE_TRAINING"
