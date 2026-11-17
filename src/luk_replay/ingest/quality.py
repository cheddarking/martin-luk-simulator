"""Deterministic market-data quality diagnostics (not silent interpolation)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from luk_replay.domain.bar import Bar


@dataclass(frozen=True, slots=True)
class DataIssue:
    code: str
    symbol: str
    timestamp: datetime | None
    detail: str
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class QualityReport:
    bar_count: int
    symbols: tuple[str, ...]
    issues: tuple[DataIssue, ...]
    first_timestamp: datetime | None
    last_timestamp: datetime | None

    @property
    def clean(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def count(self, code: str) -> int:
        return sum(issue.code == code for issue in self.issues)


def inspect_bars(bars: Iterable[Bar], *, expected_seconds: int | None = None) -> QualityReport:
    items = tuple(bars)
    seen: dict[str, Bar] = {}
    issues: list[DataIssue] = []
    counts = Counter(item.symbol for item in items)
    for bar in items:
        previous = seen.get(bar.symbol)
        if previous is not None:
            distance = (bar.timestamp.astimezone(timezone.utc)
                        - previous.timestamp.astimezone(timezone.utc)).total_seconds()
            if distance <= 0:
                issues.append(DataIssue("ordering", bar.symbol, bar.timestamp,
                                        "symbol timestamps are not strictly increasing", "error"))
            elif expected_seconds is not None and distance > expected_seconds:
                # Overnight and weekends are not assumed to be missing bars.
                if previous.timestamp.date() == bar.timestamp.date():
                    issues.append(DataIssue("intraday_gap", bar.symbol, bar.timestamp,
                                            f"{int(distance)} seconds since previous bar"))
        if bar.volume == 0:
            issues.append(DataIssue("zero_volume", bar.symbol, bar.timestamp,
                                    "zero reported volume; indicative quote may be stale"))
        if bar.range_usd == 0:
            issues.append(DataIssue("zero_range", bar.symbol, bar.timestamp,
                                    "bar has no movement; verify source quality"))
        seen[bar.symbol] = bar
    return QualityReport(
        len(items), tuple(sorted(counts)), tuple(issues),
        min((b.timestamp for b in items), default=None),
        max((b.timestamp for b in items), default=None),
    )
