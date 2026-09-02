from types import SimpleNamespace

from web.backend.services.draft_live import LiveDraftClient, overlay_live_draft


def test_selected_event_fills_next_placeholder_pick():
    client = LiveDraftClient()
    client._state = {
        "picks": [
            {"pick_number": 1, "team_id": 1, "player_id": 101, "slot_id": 0},
            {"pick_number": 2, "team_id": 7, "player_id": -1, "slot_id": 0},
        ]
    }

    client._handle("SELECTED 7 202 4")

    assert client._state["picks"][1] == {
        "pick_number": 2,
        "team_id": 7,
        "player_id": 202,
        "slot_id": 4,
    }


def test_live_error_is_recorded_as_disconnected():
    client = LiveDraftClient()

    client._handle("ERROR 1 No+team+found")

    assert client._state["connected"] is False
    assert client._state["connection_error"] == "1 No team found"


def test_cached_snapshot_remains_available_after_connection_stops():
    client = LiveDraftClient()
    client._key = (321, 2027, 1)
    client._state = {
        "draft_date": 123456,
        "connected": True,
        "updated_at": 42,
        "picks": [{"pick_number": 1, "team_id": 4, "player_id": 99, "slot_id": 0}],
    }

    class Metadata:
        league_id = 321
        year = 2027

    client.stop()
    snapshot = client.cached_snapshot(
        Metadata(),
        {"settings": {"draftSettings": {"date": 123456}}},
    )

    assert snapshot["connected"] is False
    assert snapshot["updated_at"] == 42
    assert snapshot["picks"][0]["player_id"] == 99


def test_saved_snapshot_is_reloaded_from_disk_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(
        LiveDraftClient,
        "_cache_path",
        lambda self, league_id, season: tmp_path / f"live_draft_{league_id}_{season}.json",
    )

    writer = LiveDraftClient()
    writer._key = (321, 2027, 1)
    writer._state = {
        "draft_date": 123456,
        "connected": True,
        "updated_at": 42,
        "picks": [{"pick_number": 1, "team_id": 4, "player_id": 99, "slot_id": 0}],
    }
    writer._save()

    restored = LiveDraftClient()
    snapshot = restored.cached_snapshot(
        SimpleNamespace(league_id=321, year=2027),
        {"settings": {"draftSettings": {"date": 123456}}},
    )

    assert (tmp_path / "live_draft_321_2027.json").exists()
    assert snapshot["connected"] is False
    assert snapshot["updated_at"] == 42
    assert snapshot["picks"][0]["player_id"] == 99


def test_espn_mode_overlays_saved_snapshot_onto_rest_placeholders(tmp_path, monkeypatch):
    import web.backend.services.draft_live as draft_live

    monkeypatch.setattr(
        LiveDraftClient,
        "_cache_path",
        lambda self, league_id, season: tmp_path / f"live_draft_{league_id}_{season}.json",
    )
    client = LiveDraftClient()
    monkeypatch.setattr(draft_live, "live_draft_client", client)
    monkeypatch.setattr(draft_live, "get_draft_connection_mode", lambda: "espn")

    client._key = (1, 2027, 1)
    client._state = {
        "draft_date": 99,
        "connected": True,
        "picks": [{"pick_number": 1, "team_id": 4, "player_id": 77, "slot_id": 2}],
    }
    client._save()
    client._key = None
    client._state = {"picks": []}

    merged = overlay_live_draft(
        SimpleNamespace(league_id=1, year=2027),
        {
            "draftDetail": {
                "inProgress": True,
                "picks": [{"overallPickNumber": 1, "playerId": -1, "teamId": 1}],
            },
            "settings": {"draftSettings": {"date": 99}},
        },
    )

    assert merged["draftDetail"]["picks"][0]["playerId"] == 77
    assert merged["draftDetail"]["picks"][0]["teamId"] == 4
    assert merged["draftDetail"]["liveSnapshotAvailable"] is True
    assert merged["draftDetail"]["liveSnapshotFrozen"] is True
    assert merged["draftDetail"]["liveSource"] is False


def test_espn_mode_injects_snapshot_picks_when_rest_board_is_empty(tmp_path, monkeypatch):
    import web.backend.services.draft_live as draft_live

    monkeypatch.setattr(
        LiveDraftClient,
        "_cache_path",
        lambda self, league_id, season: tmp_path / f"live_draft_{league_id}_{season}.json",
    )
    client = LiveDraftClient()
    monkeypatch.setattr(draft_live, "live_draft_client", client)
    monkeypatch.setattr(draft_live, "get_draft_connection_mode", lambda: "espn")
    client._key = (1, 2027, 1)
    client._state = {
        "draft_date": 99,
        "picks": [{"pick_number": 3, "team_id": 8, "player_id": 55, "slot_id": 1}],
    }

    merged = overlay_live_draft(
        SimpleNamespace(league_id=1, year=2027),
        {
            "draftDetail": {"inProgress": True, "picks": []},
            "settings": {"draftSettings": {"date": 99}},
        },
    )

    assert merged["draftDetail"]["picks"] == [{
        "overallPickNumber": 3,
        "playerId": 55,
        "teamId": 8,
        "lineupSlotId": 1,
    }]
    assert merged["draftDetail"]["liveSnapshotAvailable"] is True


def test_cached_snapshot_prefers_disk_picks_over_empty_dated_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(
        LiveDraftClient,
        "_cache_path",
        lambda self, league_id, season: tmp_path / f"live_draft_{league_id}_{season}.json",
    )
    writer = LiveDraftClient()
    writer._key = (1, 2027, 1)
    writer._state = {
        "draft_date": 111,
        "picks": [{"pick_number": 1, "team_id": 4, "player_id": 99, "slot_id": 0}],
    }
    writer._save()

    client = LiveDraftClient()
    client._key = (1, 2027, 1)
    client._state = {"draft_date": 222, "picks": []}

    snapshot = client.cached_snapshot(
        SimpleNamespace(league_id=1, year=2027),
        {"settings": {"draftSettings": {"date": 222}}},
    )

    assert snapshot["picks"][0]["player_id"] == 99


def test_load_keeps_disk_snapshot_when_rest_draft_date_differs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        LiveDraftClient,
        "_cache_path",
        lambda self, league_id, season: tmp_path / f"live_draft_{league_id}_{season}.json",
    )
    writer = LiveDraftClient()
    writer._key = (1, 2027, 1)
    writer._state = {
        "draft_date": 111,
        "picks": [{"pick_number": 2, "team_id": 5, "player_id": 88, "slot_id": 0}],
    }
    writer._save()

    client = LiveDraftClient()
    client._state = {"picks": [], "draft_date": 222}
    client._load(1, 2027, 222)

    assert client._state["picks"][0]["player_id"] == 88
