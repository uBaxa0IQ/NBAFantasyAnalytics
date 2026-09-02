"""Small persistent runtime overrides for connection settings changed in the UI."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _settings_path() -> Path:
    return Path(os.getenv("NBA_RUNTIME_SETTINGS_PATH", ".cache/runtime_settings.json"))


def load_runtime_settings() -> dict:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def get_runtime_league_id(fallback: int) -> int:
    value = load_runtime_settings().get("league_id")
    try:
        value = int(value)
        return value if value > 0 else int(fallback)
    except (TypeError, ValueError):
        return int(fallback)


def _save_runtime_settings(data: dict) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_runtime_league_id(league_id: int) -> None:
    league_id = int(league_id)
    if league_id <= 0:
        raise ValueError("League ID must be positive")
    data = load_runtime_settings()
    data["league_id"] = league_id
    _save_runtime_settings(data)


def get_draft_connection_mode() -> str:
    mode = str(load_runtime_settings().get("draft_connection_mode", "espn")).lower()
    return mode if mode in {"espn", "analytics"} else "espn"


def save_draft_connection_mode(mode: str) -> None:
    mode = str(mode).lower()
    if mode not in {"espn", "analytics"}:
        raise ValueError("Unknown draft connection mode")
    data = load_runtime_settings()
    data["draft_connection_mode"] = mode
    _save_runtime_settings(data)
