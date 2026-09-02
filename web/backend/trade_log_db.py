"""Local persistence for completed trade analyses."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional


# Keep the existing filename so local trade history survives this refactor.
DB_PATH = os.path.join(os.path.dirname(__file__), "admin.db")


def get_db_connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            teams_involved TEXT NOT NULL,
            team_names TEXT NOT NULL,
            players_involved TEXT NOT NULL,
            top_players TEXT NOT NULL,
            scope_mode TEXT,
            period TEXT,
            result_delta REAL,
            full_result TEXT,
            ip_address TEXT
        )
        """
    )
    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(trade_logs)").fetchall()
    }
    for column in ("team_names", "top_players", "full_result"):
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE trade_logs ADD COLUMN {column} TEXT")
    connection.commit()
    connection.close()


def log_trade(
    trade_type: str,
    teams_involved: List[int],
    team_names: List[str],
    players_involved: Dict,
    top_players: Dict,
    scope_mode: Optional[str] = None,
    period: Optional[str] = None,
    result_delta: Optional[float] = None,
    full_result: Optional[Dict] = None,
    ip_address: Optional[str] = None,
):
    connection = get_db_connection()
    connection.execute(
        """
        INSERT INTO trade_logs
        (timestamp, trade_type, teams_involved, team_names, players_involved,
         top_players, scope_mode, period, result_delta, full_result, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            trade_type,
            json.dumps(teams_involved),
            json.dumps(team_names),
            json.dumps(players_involved),
            json.dumps(top_players),
            scope_mode,
            period,
            result_delta,
            json.dumps(full_result) if full_result else None,
            ip_address,
        ),
    )
    connection.commit()
    connection.close()


init_db()
