"""Price structure derived from completed observations, never future pivots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from luk_replay.domain.bar import Bar


@dataclass(frozen=True, slots=True)
class PriceZone:
    low: Decimal
    high: Decimal
    origin: str

    def __post_init__(self) -> None:
        if self.low <= 0 or self.high < self.low:
            raise ValueError("zone requires valid positive bounds")

    def contains(self, price: Decimal, *, slack_pct: Decimal = Decimal()) -> bool:
        margin = self.high * slack_pct / Decimal(100)
        return self.low - margin <= price <= self.high + margin

    def distance_pct(self, price: Decimal) -> Decimal:
        if self.contains(price):
            return Decimal()
        boundary = self.low if price < self.low else self.high
        return abs(price - boundary) / boundary * Decimal(100)


def recent_support(bars: Sequence[Bar], *, lookback: int = 20,
                   width_pct: Decimal = Decimal("0.40")) -> PriceZone | None:
    if lookback < 2 or width_pct < 0:
        raise ValueError("invalid support window")
    if len(bars) < 2:
        return None
    recent = bars[-lookback:]
    floor = min(bar.low for bar in recent)
    return PriceZone(floor, (floor * (Decimal(1) + width_pct / 100)).quantize(Decimal("0.01")),
                     f"low-of-{len(recent)}-completed-bars")


def recent_resistance(bars: Sequence[Bar], *, lookback: int = 20) -> Decimal | None:
    if lookback < 1:
        raise ValueError("invalid resistance window")
    recent = bars[-lookback:]
    return max((bar.high for bar in recent), default=None)


def higher_lows(bars: Sequence[Bar], *, count: int = 3) -> bool:
    if count < 2:
        raise ValueError("count must be at least two")
    if len(bars) < count:
        return False
    lows = [bar.low for bar in bars[-count:]]
    return all(left < right for left, right in zip(lows, lows[1:]))
