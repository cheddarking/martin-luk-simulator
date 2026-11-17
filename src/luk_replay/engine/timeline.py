"""Stable market clock: a timestamp is processed only after its bar closes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Iterable, Iterator, Sequence

from luk_replay.domain.bar import Bar


class Priority(IntEnum):
    BAR_CLOSE = 0  # The prior bar is known before the next bar opens at this instant.
    DECISION = 5
    OPEN = 10
    STOP = 20
    AUDIT = 40


@dataclass(frozen=True, slots=True, order=True)
class Tick:
    at: datetime
    priority: Priority
    source_index: int
    symbol: str
    phase: str
    bar: Bar

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("tick time requires timezone")
        if self.phase not in {"OPEN", "CLOSE"}:
            raise ValueError("phase must be OPEN or CLOSE")

    @property
    def utc(self) -> datetime:
        return self.at.astimezone(timezone.utc)


def market_ticks(bars: Sequence[Bar]) -> tuple[Tick, ...]:
    output: list[Tick] = []
    for n, bar in enumerate(bars):
        output.append(Tick(bar.timestamp, Priority.OPEN, n, bar.symbol, "OPEN", bar))
        output.append(Tick(bar.end_time, Priority.BAR_CLOSE, n, bar.symbol, "CLOSE", bar))
    output.sort(key=lambda t: (t.utc, t.priority, t.source_index))
    return tuple(output)


def validate_timeline(ticks: Sequence[Tick]) -> None:
    previous: datetime | None = None
    opens: set[int] = set()
    for tick in ticks:
        current = tick.utc
        if previous is not None and current < previous:
            raise ValueError("market timeline is not time-ordered")
        if tick.phase == "OPEN":
            if tick.source_index in opens:
                raise ValueError("duplicate market open tick")
            opens.add(tick.source_index)
        elif tick.source_index not in opens:
            raise ValueError("market bar closed before its open")
        previous = current


def completed_at(ticks: Iterable[Tick], as_of: datetime) -> tuple[Bar, ...]:
    if as_of.tzinfo is None:
        raise ValueError("as-of time requires timezone")
    end = as_of.astimezone(timezone.utc)
    return tuple(t.bar for t in ticks if t.phase == "CLOSE" and t.utc <= end)
