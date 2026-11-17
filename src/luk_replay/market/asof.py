"""Only completed observations can enter a strategy's information set."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence

from luk_replay.domain.bar import Bar


def _require_aware(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("as-of timestamp requires timezone")
    return timestamp.astimezone(timezone.utc)


def bars_known_at(bars: Iterable[Bar], timestamp: datetime) -> tuple[Bar, ...]:
    instant = _require_aware(timestamp)
    return tuple(bar for bar in bars if bar.end_time.astimezone(timezone.utc) <= instant)


def last_completed(bars: Iterable[Bar], timestamp: datetime) -> Bar | None:
    known = bars_known_at(bars, timestamp)
    return max(known, key=lambda bar: bar.end_time) if known else None


@dataclass(frozen=True, slots=True)
class MarketView:
    as_of: datetime
    symbol: str
    one_minute: tuple[Bar, ...]
    five_minute: tuple[Bar, ...]
    daily: tuple[Bar, ...]

    def __post_init__(self) -> None:
        instant = _require_aware(self.as_of)
        for bar in (*self.one_minute, *self.five_minute, *self.daily):
            if bar.end_time.astimezone(timezone.utc) > instant:
                raise ValueError("market view contains a future or incomplete bar")
            if bar.symbol != self.symbol:
                raise ValueError("market view mixes instruments")

    def latest_close(self) -> object | None:
        return self.one_minute[-1].close if self.one_minute else None


def snapshot(symbol: str, timestamp: datetime, *, one_minute: Sequence[Bar] = (),
             five_minute: Sequence[Bar] = (), daily: Sequence[Bar] = ()) -> MarketView:
    return MarketView(timestamp, symbol,
                      bars_known_at((b for b in one_minute if b.symbol == symbol), timestamp),
                      bars_known_at((b for b in five_minute if b.symbol == symbol), timestamp),
                      bars_known_at((b for b in daily if b.symbol == symbol), timestamp))
