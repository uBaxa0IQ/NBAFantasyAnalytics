from scripts.draft_v86_ood import FIELDS, summarize


def test_ood_gate_requires_positive_model_policy_effect():
    rows = [{"completed_hero_picks": index, "baseline": "A", "selected": "B",
             "independent_h2h_delta": 0.02,
             "independent_h2h_delta_samples": {field: [0.02, 0.02] for field in FIELDS}}
            for index in range(5)]
    assert summarize(rows)["passed"]
    rows[0]["independent_h2h_delta_samples"]["model_top3"] = [-0.2, -0.2]
    rows[0]["independent_h2h_delta"] = -0.09
    assert not summarize(rows)["passed"]


def test_ood_unchanged_picks_cannot_pass():
    rows = [{"completed_hero_picks": index, "baseline": "A", "selected": "A",
             "independent_h2h_delta": 0.0,
             "independent_h2h_delta_samples": {field: [0.0] for field in FIELDS}}
            for index in range(5)]
    assert summarize(rows)["decision"] == "KEEP_EXPERIMENTAL_NO_DEPLOYMENT"
