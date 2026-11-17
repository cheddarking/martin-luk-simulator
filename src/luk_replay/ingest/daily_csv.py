"""Read Yahoo-shaped DAILY stock CSV files as exchange-local complete sessions.

The converter is intentionally independent of the user's private screener code.
Input cells may have sub-cent precision after a provider adjustment: the broker
model only represents cents, so quantization is counted and disclosed.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from luk_replay.domain.bar import Bar
from luk_replay.market.calendar import USMarketCalendar

HEADERS = frozenset({"Date", "Close", "High", "Low", "Open", "Volume"})
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.^-]{0,14}$")
CENT = Decimal("0.01")
MAX_DAILY_BYTES = 4_000_000
MAX_DAILY_ROWS = 15_000


class DailyImportError(ValueError):
    """The daily source file cannot be safely represented as historical bars."""


@dataclass(frozen=True, slots=True)
class DailyHistory:
    path: Path
    symbol: str
    bars: tuple[Bar, ...]
    sha256: str
    source_kind: str
    adjustment: str
    rounded_cells: int
    first_date: date
    last_date: date

    def __post_init__(self) -> None:
        if not self.bars or self.bars[0].symbol != self.symbol:
            raise ValueError("daily history is empty or mixes symbols")
        if self.first_date > self.last_date:
            raise ValueError("history bounds are inverted")

    @property
    def sessions(self) -> int:
        return len(self.bars)

    def provenance(self) -> dict[str, str | int]:
        return {"symbol": self.symbol, "first_date": self.first_date.isoformat(),
                "last_date": self.last_date.isoformat(), "sessions": self.sessions,
                "source": self.source_kind, "adjustment": self.adjustment,
                "sha256": self.sha256, "rounded_cells": self.rounded_cells}


def symbol_from_filename(path: Path) -> str:
    symbol = path.stem.upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise DailyImportError(f"invalid symbol filename: {path.name}")
    return symbol


def _positive_decimal(row: dict[str, str], column: str, line: int) -> Decimal:
    text = row.get(column)
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DailyImportError(f"line {line}: {column} is not a decimal") from exc
    if not value.is_finite() or value <= 0:
        raise DailyImportError(f"line {line}: {column} must be finite and positive")
    return value


def read_yahoo_daily(
    path: str | Path, *, adjustment: str = "unknown",
    source_kind: str = "yfinance_cache", calendar: USMarketCalendar | None = None,
) -> DailyHistory:
    source = Path(path)
    symbol = symbol_from_filename(source)
    if not source.is_file() or source.is_symlink():
        raise DailyImportError(f"not a regular daily price CSV: {source.name}")
    if source.stat().st_size > MAX_DAILY_BYTES:
        raise DailyImportError(f"daily CSV exceeds {MAX_DAILY_BYTES} bytes: {source.name}")
    if adjustment not in {"unknown", "yahoo_auto_adjust_false", "yahoo_auto_adjust_true"}:
        raise DailyImportError("unknown daily adjustment policy")
    schedule = calendar or USMarketCalendar()
    records: list[Bar] = []
    hasher = hashlib.sha256()
    rounded = 0
    previous: date | None = None
    try:
        # Small bounded files: exact digest of bytes imported, not a later mtime.
        hasher.update(source.read_bytes())
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = csv.DictReader(stream)
            fields = set(rows.fieldnames or [])
            if fields != HEADERS or len(rows.fieldnames or []) != len(HEADERS):
                raise DailyImportError("daily CSV requires Date,Close,High,Low,Open,Volume")
            for line, row in enumerate(rows, start=2):
                if line > MAX_DAILY_ROWS + 1:
                    raise DailyImportError(f"line {line}: daily row limit exceeded")
                if None in row or any(value is None for value in row.values()):
                    raise DailyImportError(f"line {line}: missing or unexpected field")
                try:
                    text = row["Date"].strip()
                    trading_date = date.fromisoformat(text)
                    if text != trading_date.isoformat():
                        raise ValueError("date must be YYYY-MM-DD")
                except (ValueError, TypeError) as exc:
                    raise DailyImportError(f"line {line}: date must be YYYY-MM-DD") from exc
                if previous is not None and trading_date <= previous:
                    label = "duplicate" if trading_date == previous else "out of order"
                    raise DailyImportError(f"line {line}: {label} trading date")
                try:
                    session = schedule.session(trading_date)
                except ValueError as exc:
                    raise DailyImportError(f"line {line}: market closed on {trading_date}") from exc
                raw = {name.lower(): _positive_decimal(row, name, line)
                       for name in ("Open", "High", "Low", "Close")}
                prices = {key: value.quantize(CENT, rounding=ROUND_HALF_UP)
                          for key, value in raw.items()}
                rounded += sum(prices[key] != raw[key] for key in raw)
                try:
                    vol_text = row["Volume"].strip()
                    if not vol_text.isdecimal():
                        raise ValueError("invalid integer")
                    volume = int(vol_text)
                    bar = Bar(session.open_local, symbol, volume=volume,
                              timeframe_seconds=session.trading_minutes * 60,
                              **prices)
                except ValueError as exc:
                    raise DailyImportError(f"line {line}: invalid OHLCV: {exc}") from exc
                records.append(bar)
                previous = trading_date
    except UnicodeError as exc:
        raise DailyImportError("daily CSV must be UTF-8 encoded") from exc
    if not records:
        raise DailyImportError("daily CSV contains no price bars")
    return DailyHistory(source, symbol, tuple(records), hasher.hexdigest(),
                        source_kind, adjustment, rounded,
                        records[0].timestamp.date(), records[-1].timestamp.date())
