import numpy as np

from scripts.draft_v85_action_data import feature_names
from scripts.draft_v85_action_train import evaluation_summary, labels, pair_features


def test_pair_features_keep_frozen_actor_as_zero_residual():
    names = feature_names(("FG%", "FT%"))
    matrix = np.zeros((2, len(names)), dtype=float)
    matrix[1, names.index("candidate_minus_baseline_z_FG%")] = 0.5
    matrix[1, names.index("candidate_raw_GP")] = 0.2
    matrix[0, names.index("roster_z_FG%")] = 0.1
    row = {"features": matrix.tolist(), "baseline_position": 0}

    result = pair_features(row, names)

    assert np.allclose(result[0], 0)
    assert np.linalg.norm(result[1]) > 0


def test_labels_are_paired_against_actor_and_zero_gain_does_not_pass():
    row = {"baseline_position": 0,
           "h2h_samples": {"heuristic": [[0.4, 0.4], [0.5, 0.5]],
                           "roto": [[0.4, 0.4], [0.5, 0.5]]}}
    assert np.allclose(labels(row), [0.0, 0.1])
    rows = [{"completed_hero_picks": completed, "baseline": "A", "selected": "A",
             "independent_h2h_delta": 0.0,
             "independent_h2h_delta_samples": {"heuristic": [0.0], "roto": [0.0]}}
            for completed in (0, 3, 7)]
    assert evaluation_summary(rows, "validation")["decision"] == "KEEP_FROZEN_ACTOR"
