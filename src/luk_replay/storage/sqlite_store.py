"""Transactional, local, immutable run/event storage with safe query parameters."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Any

from luk_replay.engine.replay import ReplayResult

from .schema import migrate
from .serialization import canonical_json, run_identifier, run_summary


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists()
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        migrate(self.connection)
        if not existed and self.path != Path(":memory:"):
            os.chmod(self.path, 0o600)

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, _type: type[BaseException] | None, _value: BaseException | None,
                 _trace: TracebackType | None) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def save_run(self, result: ReplayResult) -> str:
        run_id = run_identifier(result)
        summary = run_summary(result)
        with self.connection:
            self.connection.execute(
                """INSERT OR IGNORE INTO replay_runs (
                    run_id, source_digest, strategy_version, symbol,
                    initial_equity_gbp, final_equity_gbp, ending_cash_gbp,
                    decision_count, entry_count, exit_count, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, result.source_digest, result.strategy_version,
                 result.symbol, str(result.initial_equity_gbp),
                 str(result.final_equity_gbp), str(result.ending_cash_gbp),
                 len(result.decisions), len(result.entries), len(result.exits),
                 canonical_json(summary)),
            )
            self.connection.executemany(
                """INSERT OR IGNORE INTO replay_events (
                    run_id, sequence, as_of, kind, symbol, reason, event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ((run_id, event.sequence, event.normalized_timestamp(),
                  event.kind.value, event.symbol, event.reason,
                  canonical_json(event.as_record())) for event in result.events),
            )
        return run_id

    def get_summary(self, run_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT summary_json FROM replay_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return json.loads(row["summary_json"]) if row else None

    def get_events(self, run_id: str, *, limit: int | None = None,
                   offset: int = 0) -> list[dict[str, Any]]:
        if offset < 0 or limit is not None and not 1 <= limit <= 10000:
            raise ValueError("offset or event page limit is invalid")
        if limit is None:
            rows = self.connection.execute(
                "SELECT event_json FROM replay_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            )
        else:
            rows = self.connection.execute(
                """SELECT event_json FROM replay_events WHERE run_id = ?
                   ORDER BY sequence LIMIT ? OFFSET ?""", (run_id, limit, offset)
            )
        return [json.loads(row["event_json"]) for row in rows]

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("run-list limit must be between 1 and 1000")
        rows = self.connection.execute(
            """SELECT run_id, symbol, strategy_version, source_digest,
                      decision_count, entry_count, exit_count, final_equity_gbp
               FROM replay_runs ORDER BY rowid DESC LIMIT ?""", (limit,),
        )
        return [dict(row) for row in rows]

    def count_events(self, run_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM replay_events WHERE run_id = ?", (run_id,)
        ).fetchone()
        return int(row["n"])

    def exists(self, run_id: str) -> bool:
        return self.get_summary(run_id) is not None
