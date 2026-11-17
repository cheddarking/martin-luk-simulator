"""Stable indicators over already-known bars; caller owns as-of filtering."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Sequence

from luk_replay.domain.bar import Bar


def ema_series(bars: Iterable[Bar], period: int) -> tuple[Decimal, ...]:
    if period < 1:
        raise ValueError("EMA period must be positive")
    alpha = Decimal(2) / Decimal(period + 1)
    output: list[Decimal] = []
    for bar in bars:
        current = bar.close if not output else output[-1] + alpha * (bar.close - output[-1])
        output.append(current)
    return tuple(output)


def simple_moving_average(bars: Sequence[Bar], period: int) -> Decimal | None:
    if period < 1:
        raise ValueError("period must be positive")
    if len(bars) < period:
        return None
    return sum((bar.close for bar in bars[-period:]), Decimal()) / Decimal(period)


def average_volume(bars: Sequence[Bar], period: int) -> Decimal | None:
    if period < 1:
        raise ValueError("period must be positive")
    if len(bars) < period:
        return None
    return Decimal(sum(bar.volume for bar in bars[-period:])) / Decimal(period)


def average_daily_range(bars: Sequence[Bar], period: int = 20) -> Decimal | None:
    if period < 1:
        raise ValueError("period must be positive")
    if len(bars) < period:
        return None
    return sum((bar.range_usd for bar in bars[-period:]), Decimal()) / Decimal(period)


def exponential_average(values: Iterable[Decimal], period: int) -> tuple[Decimal, ...]:
    if period < 1:
        raise ValueError("period must be positive")
    alpha = Decimal(2) / Decimal(period + 1)
    output: list[Decimal] = []
    for item in values:
        output.append(item if not output else output[-1] + alpha * (item - output[-1]))
    return tuple(output)
