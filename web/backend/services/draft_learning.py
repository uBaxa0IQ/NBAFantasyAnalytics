"""Local, append-only draft decision dataset for future policy training."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(os.getenv("DRAFT_LEARNING_DB", Path(__file__).resolve().parents[1] / "draft_learning.db"))


def _connect():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS draft_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_id INTEGER NOT NULL,
            season INTEGER NOT NULL,
            team_id INTEGER NOT NULL,
            observed_pick_count INTEGER NOT NULL,
            target_overall INTEGER NOT NULL,
            roster_json TEXT NOT NULL,
            advice_json TEXT NOT NULL,
            strategy_json TEXT NOT NULL,
            actual_player_id INTEGER,
            actual_player_name TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            UNIQUE(league_id, season, team_id, observed_pick_count, target_overall)
        )
        """
    )
    return connection


def record_live_decision(
    *, league_id, season, team_id, pick_count, target_overall, roster, advice,
    adaptive_strategy, completed_picks,
):
    """Resolve earlier decisions and store the current on-clock snapshot locally."""
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        for pick in completed_picks or ():
            overall = pick.get("overallPickNumber")
            if overall is None or int(pick.get("teamId") or -1) != int(team_id):
                continue
            connection.execute(
                """
                UPDATE draft_decisions
                SET actual_player_id = ?, actual_player_name = ?, resolved_at = ?
                WHERE league_id = ? AND season = ? AND team_id = ?
                  AND target_overall = ? AND resolved_at IS NULL
                """,
                (
                    pick.get("playerId"), pick.get("player_name"), now,
                    int(league_id), int(season), int(team_id), int(overall),
                ),
            )
        if target_overall is None:
            return
        connection.execute(
            """
            INSERT OR IGNORE INTO draft_decisions (
                league_id, season, team_id, observed_pick_count, target_overall,
                roster_json, advice_json, strategy_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(league_id), int(season), int(team_id), int(pick_count), int(target_overall),
                json.dumps(roster or [], ensure_ascii=False),
                json.dumps(advice or {}, ensure_ascii=False),
                json.dumps(adaptive_strategy or {}, ensure_ascii=False),
                now,
            ),
        )


def learning_dataset_stats():
    if not DB_PATH.exists():
        return {"decisions": 0, "resolved": 0, "database": str(DB_PATH)}
    with _connect() as connection:
        decisions, resolved = connection.execute(
            "SELECT COUNT(*), SUM(CASE WHEN resolved_at IS NOT NULL THEN 1 ELSE 0 END) FROM draft_decisions"
        ).fetchone()
    return {"decisions": decisions or 0, "resolved": resolved or 0, "database": str(DB_PATH)}
