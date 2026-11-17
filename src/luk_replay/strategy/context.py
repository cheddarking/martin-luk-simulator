"""Point-in-time long-only daily context without undocumented discretion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from luk_replay.domain.bar import Bar
from luk_replay.market.anchors import anchored_vwap
from luk_replay.market.indicators import average_daily_range, average_volume, ema_series
from luk_replay.market.structure import PriceZone, recent_support


@dataclass(frozen=True, slots=True)
class DailyContext:
    symbol: str
    observed_close: Decimal
    ema_9: Decimal | None
    ema_21: Decimal | None
    ema_50: Decimal | None
    avwap: Decimal | None
    adr: Decimal | None
    volume_ratio: Decimal | None
    zone: PriceZone | None
    history_count: int
    rising: bool

    @property
    def aligned(self) -> bool:
        if any(item is None for item in (self.ema_9, self.ema_21, self.ema_50)):
            return False
        return bool(self.ema_9 > self.ema_21 > self.ema_50)


def build_daily_context(bars: Sequence[Bar], *, support_lookback: int = 20) -> DailyContext | None:
    if support_lookback < 2:
        raise ValueError("support lookback must cover at least two completed days")
    if not bars:
        return None
    symbol = bars[-1].symbol
    if any(bar.symbol != symbol for bar in bars):
        raise ValueError("daily context cannot mix instruments")
    if any(bar.timeframe_seconds < 3600 for bar in bars):
        raise ValueError("daily context requires daily observations")
    enough = len(bars) >= 50
    ema9, ema21, ema50 = (ema_series(bars, p) for p in (9, 21, 50))
    avwap = anchored_vwap(bars[-30:]) if enough else None
    prior_volume = average_volume(bars[:-1], 10)
    ratio = (Decimal(bars[-1].volume) / prior_volume
             if prior_volume is not None and prior_volume else None)
    return DailyContext(
        symbol, bars[-1].close, ema9[-1] if enough else None,
        ema21[-1] if enough else None, ema50[-1] if enough else None,
        avwap, average_daily_range(bars, 20), ratio,
        recent_support(bars, lookback=support_lookback) if enough else None,
        len(bars), enough and ema9[-1] > ema9[-5],
    )
