"""Read-only inventory of private daily price directories.

Inventory need not load millions of OHLC rows: it samples first and last date
for discovery, while the selected ticker is fully validated at replay time.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Iterable

from .daily_csv import DailyImportError, SYMBOL_RE, read_yahoo_daily
from luk_replay.market.calendar import USMarketCalendar


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    symbol: str
    path: Path
    first_date: date
    last_date: date
    source_kind: str
    adjustment: str
    bytes: int
    sessions: int
    max_gap_days: int
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        if (not SYMBOL_RE.fullmatch(self.symbol) or self.first_date > self.last_date
                or self.sessions < 1 or self.max_gap_days < 0):
            raise ValueError("invalid historical dataset record")

    @property
    def complete_six_years(self) -> bool:
        today = datetime.now(ZoneInfo("America/New_York")).date()
        try:
            six_years_ago = today.replace(year=today.year - 6)
        except ValueError:  # Feb 29 -> Feb 28 in a non-leap target year.
            six_years_ago = today.replace(year=today.year - 6, day=28)
        if self.first_date > six_years_ago or self.last_date < today - timedelta(days=7):
            return False
        if self.max_gap_days > 7:
            return False
        calendar = USMarketCalendar()
        expected = calendar.sessions(self.first_date, self.last_date)
        return self.sessions >= int(len(expected) * 0.95)

    def as_dict(self) -> dict[str, str | int | bool]:
        return {"symbol": self.symbol, "first_date": self.first_date.isoformat(),
                "last_date": self.last_date.isoformat(), "source": self.source_kind,
                "adjustment": self.adjustment, "bytes": self.bytes,
                "sessions": self.sessions, "max_gap_days": self.max_gap_days,
                "complete_six_years": self.complete_six_years}


def _first_last_date(path: Path) -> tuple[date, date, int, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = csv.reader(stream)
        header = next(rows, [])
        if not header or header[0] != "Date":
            raise DailyImportError("not a daily Yahoo-shaped CSV")
        first = next(rows, None)
        if not first:
            raise DailyImportError("empty daily history")
        earliest = date.fromisoformat(first[0])
        previous = earliest
        count = 1
        max_gap = 0
        for row in rows:
            if not row:
                continue
            current = date.fromisoformat(row[0])
            if current <= previous:
                raise DailyImportError("daily catalog dates must increase strictly")
            max_gap = max(max_gap, (current - previous).days)
            previous = current
            count += 1
    return earliest, previous, count, max_gap


def _metadata(path: Path) -> tuple[str, str, str | None]:
    sidecar = path.with_suffix(".meta.json")
    if not sidecar.is_file():
        return "yfinance_cache", "unknown", None
    try:
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        source = value.get("source", "yfinance_cache")
        adjustment = value.get("adjustment", "unknown")
        if source not in {"yfinance_cache", "yfinance_six_year"}:
            raise ValueError("unsupported history source")
        if adjustment not in {"unknown", "yahoo_auto_adjust_false", "yahoo_auto_adjust_true"}:
            raise ValueError("unsupported price adjustment")
        digest = value.get("sha256")
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or
                                   any(char not in "0123456789abcdef" for char in digest.lower())):
            raise ValueError("invalid price digest")
        return source, adjustment, digest
    except (OSError, ValueError, AttributeError) as exc:
        raise DailyImportError(f"bad provenance metadata for {path.name}: {exc}") from exc


def discover_history(folder: str | Path, *,
                     symbols: Iterable[str] | None = None) -> dict[str, HistoryRecord]:
    root = Path(folder)
    if not root.is_dir():
        raise DailyImportError(f"history directory not found: {root}")
    if symbols is None:
        paths = sorted(root.glob("*.csv"))
    else:
        names = [name.upper() for name in symbols]
        if any(not SYMBOL_RE.fullmatch(name) for name in names):
            raise DailyImportError("invalid ticker symbol in catalog filter")
        paths = [root / f"{name}.csv" for name in names]
    found: dict[str, HistoryRecord] = {}
    for path in paths:
        if path.is_symlink() or not path.is_file() or not SYMBOL_RE.fullmatch(path.stem.upper()):
            continue
        try:
            first, last, sessions, max_gap = _first_last_date(path)
            source, adjustment, expected_sha256 = _metadata(path)
        except (OSError, UnicodeError, csv.Error, ValueError):
            # Non-price CSVs in the Windows screener root are not listed as data.
            continue
        found[path.stem.upper()] = HistoryRecord(
            path.stem.upper(), path, first, last, source, adjustment,
            path.stat().st_size, sessions, max_gap, expected_sha256,
        )
    return found


def select_history(folder: str | Path, symbol: str, *, as_of: datetime | None = None):
    """Validate selected source, then hide candles not yet known at the as-of time."""
    name = symbol.upper()
    if not SYMBOL_RE.fullmatch(name):
        raise DailyImportError("invalid ticker symbol")
    records = discover_history(folder, symbols=[name])
    if name not in records:
        raise DailyImportError(f"no cached daily prices for {name}")
    record = records[name]
    history = read_yahoo_daily(record.path, adjustment=record.adjustment,
                               source_kind=record.source_kind)
    if record.expected_sha256 and history.sha256 != record.expected_sha256:
        raise DailyImportError(f"price digest mismatch for {name}; private cache changed")
    cutoff = as_of or datetime.now(ZoneInfo("America/New_York"))
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise DailyImportError("history as-of timestamp must include a timezone")
    completed = tuple(bar for bar in history.bars if bar.end_time <= cutoff)
    if not completed:
        raise DailyImportError(f"no completed daily bars for {name} at requested time")
    return replace(history, bars=completed,
                   last_date=completed[-1].timestamp.date())
