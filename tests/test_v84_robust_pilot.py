from scripts.draft_v84_robust_pilot import interval, jobs_for, settings, summarize


def test_pilot_covers_both_formats_multiple_rounds_and_target_seat():
    jobs = jobs_for(settings())
    assert len(jobs) == 48
    assert {job[0]["id"] for job in jobs} == {"main-c11-t14-r13", "s8-t10-r13"}
    assert {job[2] for job in jobs} == {0, 3, 7}
    assert {job[1] for job in jobs if job[0]["id"] == "main-c11-t14-r13"} >= {5}


def test_interval_and_summary_do_not_promote_zero_h2h_gain():
    rows = []
    for format_id in ("main-c11-t14-r13", "s8-t10-r13"):
        for completed in (0, 3, 7):
            rows.append({"format_id": format_id, "seat": 5,
                         "completed_hero_picks": completed,
                         "baseline": "A", "selected": "A",
                         "independent_h2h_delta": 0.0,
                         "independent_h2h_delta_samples": {"heuristic": [0.0], "roto": [0.0]}})
    assert interval([0.0, 0.0])["ci95"] == [0.0, 0.0]
    assert summarize(rows)["decision"] == "DO_NOT_TRAIN_YET"
