"""Aggregate completed bars on exchange-local session boundaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable

from luk_replay.domain.bar import Bar

from .asof import bars_known_at


def aggregate_bars(bars: Iterable[Bar], seconds: int, *, asof: datetime | None = None,
                   require_complete: bool = True) -> tuple[Bar, ...]:
    items = tuple(bars)
    if not items:
        return ()
    if seconds <= 0 or seconds % items[0].timeframe_seconds != 0:
        raise ValueError("target aggregation must be an integral multiple of source timeframe")
    for bar in items:
        if bar.timeframe_seconds != items[0].timeframe_seconds:
            raise ValueError("mixed source timeframes cannot be aggregated")
    if asof is not None:
        items = bars_known_at(items, asof)
    groups: dict[tuple[str, datetime], list[Bar]] = defaultdict(list)
    step = items[0].timeframe_seconds
    for bar in items:
        # Anchor windows to 09:30 exchange time, never UTC midnight.
        opening = bar.timestamp.replace(hour=9, minute=30, second=0, microsecond=0)
        delta = int((bar.timestamp - opening).total_seconds())
        if delta < 0:
            continue
        window = opening + timedelta(seconds=(delta // seconds) * seconds)
        groups[(bar.symbol, window)].append(bar)
    aggregated: list[Bar] = []
    for (symbol, window), subset in sorted(groups.items(), key=lambda pair: pair[0][1]):
        subset.sort(key=lambda bar: bar.timestamp.astimezone(timezone.utc))
        expected = seconds // step
        if require_complete:
            if len(subset) != expected:
                continue
            if any(bar.timestamp != window + timedelta(seconds=n * step)
                   for n, bar in enumerate(subset)):
                continue
        aggregate = Bar(window, symbol, subset[0].open,
                        max(bar.high for bar in subset), min(bar.low for bar in subset),
                        subset[-1].close, sum(bar.volume for bar in subset), seconds)
        if asof is None or aggregate.end_time <= asof:
            aggregated.append(aggregate)
    return tuple(aggregated)
