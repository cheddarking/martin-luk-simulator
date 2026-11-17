"""Validated local replay/import API; never invoke external market endpoints."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from luk_replay.engine.replay import ReplayResult, replay
from luk_replay.engine.daily_replay import replay_daily
from luk_replay.ingest.csv_import import CSVImportError, read_bars
from luk_replay.ingest.daily_csv import DailyImportError, SYMBOL_RE
from luk_replay.ingest.history_catalog import discover_history, select_history
from luk_replay.storage.serialization import run_summary, safe_value
from luk_replay.storage.sqlite_store import SQLiteStore


class ReplayInput(BaseModel):
    bars_csv: str = Field(min_length=10, max_length=2_000_000)
    daily_csv: str | None = Field(default=None, max_length=2_000_000)


def db_for(request: Request) -> SQLiteStore:
    return SQLiteStore(request.app.state.db_path)


def public_payload(result: ReplayResult, bars: tuple[Any, ...], *,
                   source_kind: str | None = None, adjustment: str = "unknown",
                   timeframe: str = "minute") -> dict[str, Any]:
    return {
        "summary": safe_value(run_summary(result)),
        "series": [{"timestamp": b.timestamp.isoformat(), "end_time": b.end_time.isoformat(),
                    "close": str(b.close),
                    "open": str(b.open), "high": str(b.high), "low": str(b.low),
                    "volume": b.volume} for b in bars],
        "decisions": [{"as_of": d.as_of.isoformat(), "reason": d.reason,
                       "description": d.description, "accepted": d.accepted,
                       "evidence": list(d.evidence)} for d in result.decisions],
        "events": [event.as_record() for event in result.events],
        "source_kind": source_kind or result.source_kind,
        "adjustment": adjustment if adjustment != "unknown" else result.adjustment,
        "timeframe": timeframe if timeframe != "minute" else result.timeframe,
    }


def router() -> APIRouter:
    endpoints = APIRouter(prefix="/api")

    @endpoints.get("/history")
    def history_catalog(request: Request, q: str = "", limit: int = 100) -> dict[str, Any]:
        if len(q) > 15 or limit < 1 or limit > 300:
            raise HTTPException(status_code=422, detail="invalid ticker filter or limit")
        folder = request.app.state.history_dir
        if not folder.is_dir():
            return {"count": 0, "symbols": [], "limited": False}
        prefix = q.strip().upper()
        # Name-only scan is cheap even on a Windows mount; validate only the
        # small selected page with is_file/is_symlink before exposing records.
        paths = (path for path in folder.glob("*.csv")
                 if SYMBOL_RE.fullmatch(path.stem.upper()))
        names = sorted(path.stem.upper() for path in paths if path.stem.upper().startswith(prefix))
        if not prefix:
            preferred = ("AAPL", "MSFT", "NVDA", "QQQ", "IWM")
            names = [name for name in preferred if name in names] + [
                name for name in names if name not in preferred]
        entries = discover_history(folder, symbols=names[:limit])
        matched = [record.as_dict() for record in entries.values()]
        return {"count": len(names), "symbols": matched,
                "limited": len(names) > limit}

    @endpoints.post("/history/{symbol}/replay")
    def daily_replay(symbol: str, request: Request,
                     start_date: date | None = None, end_date: date | None = None
                     ) -> dict[str, Any]:
        try:
            history = select_history(request.app.state.history_dir, symbol)
            result = replay_daily(history, start_date=start_date, end_date=end_date)
        except DailyImportError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with db_for(request) as store:
            identifier = store.save_run(result)
        selected = tuple(bar for bar in history.bars
                         if (start_date is None or bar.timestamp.date() >= start_date)
                         and (end_date is None or bar.timestamp.date() <= end_date))
        return {"run_id": identifier,
                **public_payload(result, selected, source_kind=history.source_kind,
                                 adjustment=history.adjustment, timeframe="daily"),
                "history": history.provenance()}

    @endpoints.post("/replay")
    def create_replay(payload: ReplayInput, request: Request) -> dict[str, Any]:
        # Generated filenames and a dedicated temporary directory prevent
        # user-controlled filesystem paths or leaking source CSVs into runs.
        try:
            with tempfile.TemporaryDirectory(prefix="luk-replay-import-") as root:
                source = Path(root) / "intraday.csv"
                source.write_text(payload.bars_csv, encoding="utf-8")
                bars = read_bars(source)
                daily = ()
                if payload.daily_csv:
                    daily_file = Path(root) / "daily.csv"
                    daily_file.write_text(payload.daily_csv, encoding="utf-8")
                    daily = read_bars(daily_file, timeframe_seconds=86400)
                digest = hashlib.sha256(payload.bars_csv.encode("utf-8")).hexdigest()
                result = replay(bars, daily=daily, source_digest=digest)
        except (CSVImportError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        with db_for(request) as store:
            identifier = store.save_run(result)
        return {"run_id": identifier, **public_payload(result, bars)}

    @endpoints.get("/runs")
    def runs(request: Request, limit: int = 30) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise HTTPException(status_code=422, detail="limit must be 1–100")
        with db_for(request) as store:
            return {"runs": store.list_runs(limit=limit)}

    @endpoints.get("/runs/{run_id}")
    def one_run(run_id: str, request: Request) -> dict[str, Any]:
        with db_for(request) as store:
            summary = store.get_summary(run_id)
        if summary is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run_id": run_id, "summary": summary}

    @endpoints.get("/runs/{run_id}/events")
    def events(run_id: str, request: Request, offset: int = 0, limit: int = 1000
              ) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 1000:
            raise HTTPException(status_code=422, detail="invalid event page")
        with db_for(request) as store:
            if not store.exists(run_id):
                raise HTTPException(status_code=404, detail="run not found")
            items = store.get_events(run_id, limit=limit, offset=offset)
            total = store.count_events(run_id)
        return {"run_id": run_id, "total": total, "offset": offset,
                "limit": limit, "events": items}

    return endpoints
