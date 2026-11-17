"""Anchored volume-weighted average prices over observed bars only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Iterable, Sequence

from luk_replay.domain.bar import Bar


def anchored_vwap(bars: Iterable[Bar], *, from_time: datetime | None = None,
                  precision: Decimal = Decimal("0.0001")) -> Decimal | None:
    numerator = Decimal()
    total_volume = 0
    for bar in bars:
        if from_time is not None and bar.timestamp < from_time:
            continue
        numerator += bar.typical * bar.volume
        total_volume += bar.volume
    if total_volume == 0:
        return None
    return (numerator / Decimal(total_volume)).quantize(precision)


def anchored_vwap_series(bars: Iterable[Bar], *, from_time: datetime | None = None
                         ) -> tuple[Decimal | None, ...]:
    numerator, total = Decimal(), 0
    output: list[Decimal | None] = []
    for bar in bars:
        if from_time is not None and bar.timestamp < from_time:
            output.append(None)
            continue
        numerator += bar.typical * bar.volume
        total += bar.volume
        output.append((numerator / Decimal(total)).quantize(Decimal("0.0001"))
                      if total else None)
    return tuple(output)


def highest_volume_anchor(bars: Sequence[Bar], lookback: int = 30) -> datetime | None:
    if lookback < 1:
        raise ValueError("lookback must be positive")
    candidates = bars[-lookback:]
    if not candidates:
        return None
    # First winner on ties: stable across replays and file imports.
    return max(candidates, key=lambda bar: bar.volume).timestamp
