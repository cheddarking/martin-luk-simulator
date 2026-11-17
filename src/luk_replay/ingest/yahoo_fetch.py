"""Opt-in, bounded Yahoo/yfinance DAILY history downloader for private use.

No import of yfinance occurs when replaying offline. No acquired prices or
provenance sidecars belong in the public source tree; the default location is
outside the repository, and an in-repo location must be `.local-data/`.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .daily_csv import DailyImportError, SYMBOL_RE, read_yahoo_daily
from luk_replay.market.calendar import USMarketCalendar

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "QQQ", "IWM")
FIELDNAMES = ("Date", "Close", "High", "Low", "Open", "Volume")
REPO_ROOT = Path(__file__).resolve().parents[3]
Provider = Callable[[str, date, date], Sequence[Mapping[str, object]]]


class FetchError(ValueError):
    """A provider response or private destination is not safe for a local cache."""


@dataclass(frozen=True, slots=True)
class FetchRecord:
    symbol: str
    first_date: date
    last_date: date
    sessions: int
    sha256: str
    adjustment: str
    complete_six_years: bool
    corporate_action_dates: tuple[str, ...]
    path: Path

    def as_dict(self) -> dict[str, object]:
        return {"symbol": self.symbol, "first_date": self.first_date.isoformat(),
                "last_date": self.last_date.isoformat(), "sessions": self.sessions,
                "sha256": self.sha256, "adjustment": self.adjustment,
                "complete_six_years": self.complete_six_years,
                "corporate_action_dates": list(self.corporate_action_dates),
                "private_cache_path": str(self.path)}


@dataclass(frozen=True, slots=True)
class FetchReport:
    requested_start: date
    requested_end_exclusive: date
    results: dict[str, FetchRecord]
    errors: dict[str, str]

    @property
    def complete(self) -> bool:
        return bool(self.results) and not self.errors and all(
            result.complete_six_years for result in self.results.values())

    def as_dict(self) -> dict[str, object]:
        return {"requested_start": self.requested_start.isoformat(),
                "requested_end_exclusive": self.requested_end_exclusive.isoformat(),
                "complete": self.complete,
                "results": {key: value.as_dict() for key, value in self.results.items()},
                "errors": self.errors}


def _private_destination(folder: str | Path) -> Path:
    target = Path(folder).expanduser().resolve()
    try:
        relative = target.relative_to(REPO_ROOT)
    except ValueError:
        return target
    if not relative.parts or relative.parts[0] != ".local-data":
        raise FetchError("price files must be saved in a private ignored cache, not public source")
    return target


def _provider_rows(symbol: str, start: date, end: date) -> list[dict[str, object]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise FetchError("yfinance is missing; install optional data dependencies locally") from exc
    frame = yf.Ticker(symbol).history(
        start=start.isoformat(), end=end.isoformat(), interval="1d",
        auto_adjust=False, actions=True,
    )
    if frame is None or frame.empty:
        raise FetchError(f"Yahoo returned no daily stock bars for {symbol}")
    needed = {"Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(frame.columns):
        raise FetchError(f"Yahoo response for {symbol} lacks OHLCV columns")
    result: list[dict[str, object]] = []
    for timestamp, row in frame.iterrows():
        price_date = timestamp.date()
        try:
            volume = Decimal(str(row["Volume"]))
        except (InvalidOperation, KeyError, TypeError) as exc:
            raise FetchError(f"invalid volume for {symbol} on {price_date}") from exc
        if not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
            raise FetchError(f"non-integer volume for {symbol} on {price_date}")
        result.append({"Date": price_date.isoformat(),
                       **{name: row[name] for name in needed if name != "Volume"},
                       "Volume": int(volume),
                       "Stock Splits": row.get("Stock Splits", 0),
                       "Dividends": row.get("Dividends", 0)})
    return result


def _coverage(start: date, end: date, first: date, last: date, sessions: int) -> bool:
    if (end - start).days < 6 * 365 - 2:
        return False
    if first > start + timedelta(days=7) or last < end - timedelta(days=7):
        return False
    expected = len(USMarketCalendar().sessions(start, end - timedelta(days=1)))
    return sessions >= int(expected * 0.95)


def fetch_history(
    symbols: Sequence[str], *, start: date, end: date,
    cache_dir: str | Path, fetcher: Provider | None = None,
    pause_seconds: float = 0.4, overwrite: bool = False,
) -> FetchReport:
    """Fetch a small explicit ticker set. End date is exclusive.

    For an isolated coding VM, run only `history status` and `replay-daily` on
    an already provisioned cache; never call this function from those paths.
    """
    if start >= end or (end - start).days > 365 * 12:
        raise FetchError("fetch date range must be positive and at most 12 years")
    if not symbols or len(symbols) > 10 or pause_seconds < 0:
        raise FetchError("supply between 1 and 10 symbols and a non-negative pause")
    names = [name.strip().upper() for name in symbols]
    if any(not SYMBOL_RE.fullmatch(name) for name in names) or len(names) != len(set(names)):
        raise FetchError("invalid or duplicate stock symbol")
    destination = _private_destination(cache_dir)
    destination.mkdir(parents=True, exist_ok=True)
    provider = fetcher or _provider_rows
    results: dict[str, FetchRecord] = {}
    errors: dict[str, str] = {}
    for n, name in enumerate(names):
        final_csv = destination / f"{name}.csv"
        final_meta = destination / f"{name}.meta.json"
        if final_csv.exists() and not overwrite:
            errors[name] = "existing private cache preserved (pass --replace to refresh)"
            continue
        try:
            try:
                rows = provider(name, start, end)
            except Exception as exc:
                raise FetchError(f"provider failed for {name}: {type(exc).__name__}: {exc}") from exc
            if not rows:
                raise FetchError("provider returned an empty price series")
            with tempfile.TemporaryDirectory(prefix=".fetch-", dir=destination) as staging:
                temporary = Path(staging) / f"{name}.csv"
                with temporary.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=FIELDNAMES, extrasaction="ignore")
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({key: row.get(key) for key in FIELDNAMES})
                candidate = read_yahoo_daily(temporary, adjustment="yahoo_auto_adjust_false",
                                             source_kind="yfinance_six_year")
                complete = _coverage(start, end, candidate.first_date,
                                     candidate.last_date, len(candidate.bars))
                action_dates = tuple(str(row["Date"]) for row in rows if
                                     str(row.get("Stock Splits", 0)) not in {"0", "0.0", "None"}
                                     or str(row.get("Dividends", 0)) not in {"0", "0.0", "None"})
                metadata = {"source": "yfinance_six_year",
                            "adjustment": "yahoo_auto_adjust_false",
                            "requested_start": start.isoformat(),
                            "requested_end_exclusive": end.isoformat(),
                            "first_date": candidate.first_date.isoformat(),
                            "last_date": candidate.last_date.isoformat(),
                            "sha256": candidate.sha256,
                            "complete_six_years": complete,
                            "corporate_action_dates": action_dates,
                            "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
                temporary_meta = Path(staging) / f"{name}.meta.json"
                temporary_meta.write_text(json.dumps(metadata, sort_keys=True, indent=2),
                                          encoding="utf-8")
                os.replace(temporary, final_csv)
                os.replace(temporary_meta, final_meta)
                results[name] = FetchRecord(
                    name, candidate.first_date, candidate.last_date,
                    len(candidate.bars), candidate.sha256,
                    "yahoo_auto_adjust_false", complete, action_dates, final_csv,
                )
        except (FetchError, DailyImportError, OSError, ValueError, TypeError, csv.Error) as exc:
            errors[name] = str(exc)
        if n < len(names) - 1 and pause_seconds:
            time.sleep(pause_seconds)
    return FetchReport(start, end, results, errors)
