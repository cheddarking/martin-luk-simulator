"""Versioned SQLite schema for reproducible replay events and runs."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1
DDL = (
    """CREATE TABLE IF NOT EXISTS replay_runs (
        run_id TEXT PRIMARY KEY,
        source_digest TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        symbol TEXT NOT NULL,
        initial_equity_gbp TEXT NOT NULL,
        final_equity_gbp TEXT NOT NULL,
        ending_cash_gbp TEXT NOT NULL,
        decision_count INTEGER NOT NULL CHECK(decision_count >= 0),
        entry_count INTEGER NOT NULL CHECK(entry_count >= 0),
        exit_count INTEGER NOT NULL CHECK(exit_count >= 0),
        summary_json TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS replay_events (
        run_id TEXT NOT NULL REFERENCES replay_runs(run_id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL CHECK(sequence >= 0),
        as_of TEXT NOT NULL,
        kind TEXT NOT NULL,
        symbol TEXT NOT NULL,
        reason TEXT NOT NULL,
        event_json TEXT NOT NULL,
        PRIMARY KEY(run_id, sequence)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_events_run_time ON replay_events (run_id, as_of)",
)


def migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise ValueError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        for statement in DDL:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
