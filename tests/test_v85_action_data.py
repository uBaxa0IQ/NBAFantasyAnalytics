from scripts.draft_v85_action_data import cases_and_jobs, feature_names, reliability, settings


def test_data_splits_are_disjoint_and_holdout_is_not_generated():
    jobs = cases_and_jobs(settings())
    assert len(jobs) == 72
    train = {job[4] for job in jobs if job[0] == "train"}
    validation = {job[4] for job in jobs if job[0] == "validation"}
    assert train.isdisjoint(validation)
    assert {job[0] for job in jobs} == {"train", "validation"}
    assert {job[2] for job in jobs} == {5}


def test_feature_schema_and_split_half_reliability():
    categories = ("FG%", "FT%")
    assert "candidate_minus_baseline_z_FG%" in feature_names(categories)
    row = {"baseline_position": 0,
           "h2h_samples": {"heuristic": [[0.4, 0.4, 0.4, 0.4], [0.5, 0.5, 0.5, 0.5]],
                           "roto": [[0.4, 0.4, 0.4, 0.4], [0.5, 0.5, 0.5, 0.5]]}}
    result = reliability([row])
    assert result["split_half_top1_agreement"] == 1.0
    assert result["cross_selected_h2h_gain"]["mean"] > 0
