from core.league_metadata import LeagueMetadata
from core.runtime_settings import (
    get_draft_connection_mode,
    get_runtime_league_id,
    load_runtime_settings,
    save_draft_connection_mode,
    save_runtime_league_id,
)


def test_runtime_league_id_is_persisted(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    monkeypatch.setenv("NBA_RUNTIME_SETTINGS_PATH", str(path))

    assert get_runtime_league_id(123) == 123

    save_runtime_league_id(987654)

    assert get_runtime_league_id(123) == 987654
    assert load_runtime_settings()["league_id"] == 987654


def test_league_metadata_uses_runtime_league_id(monkeypatch, tmp_path):
    monkeypatch.setenv("NBA_RUNTIME_SETTINGS_PATH", str(tmp_path / "runtime.json"))
    save_runtime_league_id(456)

    metadata = LeagueMetadata()

    assert metadata.league_id == 456


def test_draft_connection_mode_defaults_to_espn_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("NBA_RUNTIME_SETTINGS_PATH", str(tmp_path / "runtime.json"))

    assert get_draft_connection_mode() == "espn"

    save_draft_connection_mode("analytics")

    assert get_draft_connection_mode() == "analytics"
    assert load_runtime_settings()["draft_connection_mode"] == "analytics"
