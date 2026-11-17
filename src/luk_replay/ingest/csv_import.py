"""Safe local CSV importer: all errors include a source location."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from luk_replay.domain.bar import Bar

from .schema import ImportSchema


class CSVImportError(ValueError):
    """A source file violates the documented OHLCV input schema."""


def _decode_bar(row: dict[str, str], line: int, timeframe_seconds: int) -> Bar:
    try:
        stamp = datetime.fromisoformat(row["timestamp"])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise CSVImportError(f"line {line}: timestamp requires a timezone offset")
        values = {name: Decimal(row[name]) for name in ("open", "high", "low", "close")}
        return Bar(
            timestamp=stamp, symbol=row["symbol"].strip().upper(),
            volume=int(row["volume"]), timeframe_seconds=timeframe_seconds, **values,
        )
    except CSVImportError:
        raise
    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        raise CSVImportError(f"line {line}: invalid bar: {exc}") from exc


def read_bars(
    path: str | Path, *, schema: ImportSchema | None = None, timeframe_seconds: int = 60,
) -> tuple[Bar, ...]:
    """Read monotonic, nonduplicate bars, preserving file order and explicit offsets.

    Timestamps are compared in UTC; local offsets may change on DST boundaries.
    Concurrent symbols may share one timestamp but a symbol may not duplicate one.
    """
    source = Path(path)
    contract = schema or ImportSchema()
    if source.suffix.lower() != ".csv":
        raise CSVImportError("only .csv inputs are supported")
    if not source.is_file():
        raise CSVImportError(f"not a regular CSV file: {source}")
    if source.stat().st_size > contract.max_bytes:
        raise CSVImportError("CSV exceeds size limit")
    output: list[Bar] = []
    seen: set[tuple[str, datetime]] = set()
    previous: datetime | None = None
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            try:
                contract.validate_header(reader.fieldnames)
            except ValueError as exc:
                raise CSVImportError(str(exc)) from exc
            for line, row in enumerate(reader, start=2):
                if line > contract.max_rows + 1:
                    raise CSVImportError(f"line {line}: CSV row limit exceeded")
                if None in row:
                    raise CSVImportError(f"line {line}: unexpected extra field")
                bar = _decode_bar(row, line, timeframe_seconds)
                utc = bar.timestamp.astimezone(timezone.utc)
                key = (bar.symbol, utc)
                if key in seen:
                    raise CSVImportError(f"line {line}: duplicate symbol/timestamp")
                if previous is not None and utc < previous:
                    raise CSVImportError(f"line {line}: timestamps out of order")
                output.append(bar)
                seen.add(key)
                previous = utc
    except UnicodeError as exc:
        raise CSVImportError("CSV must use UTF-8 encoding") from exc
    if not output:
        raise CSVImportError("CSV contains no price bars")
    return tuple(output)
