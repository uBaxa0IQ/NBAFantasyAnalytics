import json

from scripts import draft_v825_projected_precision as v825


def test_v825_uses_real_projected_snapshot_and_more_rollouts():
    settings = json.loads(v825.CONFIG.read_text(encoding="utf-8"))

    assert settings["snapshot"].endswith("standard8-2027-projected-v1.json")
    assert settings["audit_rollouts"] == 16
    assert settings["terminal_draws"] == 4
