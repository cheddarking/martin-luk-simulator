"""Offline CLI for generating fixtures, importing CSV and inspecting runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from .engine.replay import replay
from .engine.daily_replay import replay_daily
from .ingest.catalog import catalog_path
from .ingest.csv_import import CSVImportError, read_bars
from .ingest.synthetic import make_daily_lookback, make_session, write_session
from .ingest.daily_csv import DailyImportError
from .ingest.history_catalog import discover_history, select_history
from .ingest.yahoo_fetch import DEFAULT_SYMBOLS, fetch_history
from .market.calendar import USMarketCalendar
from .storage.serialization import run_summary, safe_value
from .storage.sqlite_store import SQLiteStore


def default_history_dir() -> Path:
    override = os.getenv("LUK_REPLAY_DATA_DIR")
    return Path(override).expanduser() if override else (
        Path.home() / ".local" / "share" / "luk-replay" / "history")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luk-replay", description="Offline educational trading-system simulator"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("inspect", help="validate a local CSV and report provenance")
    scan.add_argument("csv", type=Path)
    scan.add_argument("--seconds", type=int, default=60)
    fixture = sub.add_parser("generate", help="create reproducible synthetic prices")
    fixture.add_argument("csv", type=Path)
    fixture.add_argument("--scenario", choices=("pullback", "steady", "gap_down", "chop", "breakout"),
                         default="pullback")
    fixture.add_argument("--date", default="2026-11-16")
    fixture.add_argument("--minutes", type=int, default=390)
    fixture.add_argument("--initial", type=Decimal, default=Decimal("115.00"))
    fixture.add_argument("--daily-lookback", action="store_true",
                         help="generate 60 earlier synthetic daily bars for this date")
    run = sub.add_parser("replay", help="replay a local intraday CSV without broker access")
    run.add_argument("csv", type=Path)
    run.add_argument("--daily-csv", type=Path, help="pre-existing daily lookback, if supplied")
    run.add_argument("--no-store", action="store_true", help="leave no on-disk run history")
    run.add_argument("--db", type=Path,
                     default=Path.home() / ".local" / "share" / "luk-replay" / "runs.db")
    history = sub.add_parser("history", help="inspect or fetch private daily stock history")
    history_cmd = history.add_subparsers(dest="history_command", required=True)
    status = history_cmd.add_parser("status", help="inspect an existing cache without network access")
    status.add_argument("--source-dir", type=Path, default=default_history_dir())
    status.add_argument("--symbols", nargs="*", default=[])
    acquire = history_cmd.add_parser("fetch", help="explicit Yahoo daily download to private cache")
    acquire.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    acquire.add_argument("--cache-dir", type=Path, default=default_history_dir())
    acquire.add_argument("--start", help="YYYY-MM-DD; defaults to six calendar years ago")
    acquire.add_argument("--end", help="exclusive YYYY-MM-DD; defaults to tomorrow")
    acquire.add_argument("--replace", action="store_true", help="replace an existing private ticker cache")
    acquire.add_argument("--pause", type=float, default=0.4)
    daily = sub.add_parser("replay-daily", help="replay cached real daily bars offline")
    daily.add_argument("symbol")
    daily.add_argument("--source-dir", type=Path, default=default_history_dir())
    daily.add_argument("--start-date", help="optional simulation start, retaining earlier lookback")
    daily.add_argument("--end-date", help="optional simulation end")
    daily.add_argument("--no-store", action="store_true")
    daily.add_argument("--db", type=Path,
                       default=Path.home() / ".local" / "share" / "luk-replay" / "runs.db")
    market = sub.add_parser("market-day", help="inspect a US market session offline")
    market.add_argument("date", help="exchange-local date, YYYY-MM-DD")
    serve = sub.add_parser("serve", help="serve local replay inspector")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--db", type=Path,
                       default=Path.home() / ".local" / "share" / "luk-replay" / "runs.db")
    serve.add_argument("--source-dir", type=Path, default=default_history_dir(),
                       help="private local daily CSV cache; no network calls in server")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect":
            entry, report = catalog_path(args.csv, timeframe_seconds=args.seconds)
            print(json.dumps({"source": entry.as_dict(), "issues": [
                {"code": issue.code, "symbol": issue.symbol, "detail": issue.detail}
                for issue in report.issues]}, indent=2))
        elif args.command == "generate":
            if args.daily_lookback:
                through = date.fromisoformat(args.date) - timedelta(days=1)
                calendar = USMarketCalendar()
                while not calendar.is_open(through):
                    through -= timedelta(days=1)
                bars = make_daily_lookback(through=through)
            else:
                bars = make_session(args.date, scenario=args.scenario,
                                    minutes=args.minutes, initial=args.initial)
            path = write_session(args.csv, bars)
            print(f"Generated synthetic session: {path} ({len(bars)} bars)")
        elif args.command == "replay":
            entry, _quality = catalog_path(args.csv)
            intraday = read_bars(args.csv)
            daily = read_bars(args.daily_csv, timeframe_seconds=86400) if args.daily_csv else ()
            result = replay(intraday, daily=daily, source_digest=entry.sha256)
            summary = safe_value(run_summary(result))
            if not args.no_store:
                with SQLiteStore(args.db) as store:
                    summary["run_id"] = store.save_run(result)
            print(json.dumps(summary, indent=2, sort_keys=True))
        elif args.command == "history":
            if args.history_command == "status":
                records = discover_history(
                    args.source_dir, symbols=args.symbols if args.symbols else None)
                names = [name.upper() for name in args.symbols] if args.symbols else sorted(records)
                print(json.dumps({"count": len([name for name in names if name in records]),
                                  "symbols": {name: records[name].as_dict()
                                              for name in names if name in records},
                                  "missing": [name for name in names if name not in records]},
                                 indent=2, sort_keys=True))
            elif args.history_command == "fetch":
                today = date.today()
                try:
                    default_start = today.replace(year=today.year - 6)
                except ValueError:
                    default_start = today.replace(year=today.year - 6, day=28)
                beginning = date.fromisoformat(args.start) if args.start else default_start
                until = date.fromisoformat(args.end) if args.end else today + timedelta(days=1)
                report = fetch_history(args.symbols, start=beginning, end=until,
                                       cache_dir=args.cache_dir, overwrite=args.replace,
                                       pause_seconds=args.pause)
                print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
                if not report.complete:
                    return 3  # Partial or failed fetch is not success.
        elif args.command == "replay-daily":
            history = select_history(args.source_dir, args.symbol)
            result = replay_daily(
                history,
                start_date=date.fromisoformat(args.start_date) if args.start_date else None,
                end_date=date.fromisoformat(args.end_date) if args.end_date else None,
            )
            summary = safe_value(run_summary(result))
            summary.update({"source": history.source_kind, "adjustment": history.adjustment,
                            "timeframe": "daily", "first_date": history.first_date.isoformat(),
                            "last_date": history.last_date.isoformat(),
                            "rounded_cells": history.rounded_cells})
            if not args.no_store:
                with SQLiteStore(args.db) as store:
                    summary["run_id"] = store.save_run(result)
            print(json.dumps(summary, indent=2, sort_keys=True))
        elif args.command == "market-day":
            session = USMarketCalendar().session(date.fromisoformat(args.date))
            print(json.dumps({"date": session.trading_date.isoformat(),
                              "open_local": session.open_local.isoformat(),
                              "close_local": session.close_local.isoformat(),
                              "open_utc": session.open_utc.isoformat(),
                              "close_utc": session.close_utc.isoformat(),
                              "early_close": session.early_close}, indent=2))
        elif args.command == "serve":
            if args.host not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("local inspector binds only to loopback")
            import uvicorn
            from .web.app import create_app
            uvicorn.run(create_app(db_path=args.db, history_dir=args.source_dir),
                        host=args.host, port=args.port)
        return 0
    except (CSVImportError, DailyImportError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
