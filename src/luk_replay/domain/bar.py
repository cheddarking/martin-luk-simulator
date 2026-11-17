"""Validated, immutable, timestamped OHLCV observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .units import UnitError, decimal_of, quantize_usd


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    timeframe_seconds: int = 60

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp requires a timezone offset")
        if not self.symbol or not self.symbol.replace(".", "").replace("-", "").isalnum():
            raise ValueError("symbol must use letters, numbers, dots or hyphens")
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, quantize_usd(getattr(self, name)))
        if self.low <= 0 or self.high < self.low:
            raise ValueError("high/low must describe a positive range")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("OHLC values fall outside the high/low range")
        if isinstance(self.volume, bool) or not isinstance(self.volume, int) or self.volume < 0:
            raise ValueError("volume must be a non-negative integer")
        if self.timeframe_seconds <= 0:
            raise ValueError("timeframe_seconds must be positive")

    @property
    def end_time(self) -> datetime:
        from datetime import timedelta
        return self.timestamp + timedelta(seconds=self.timeframe_seconds)

    @property
    def typical(self) -> Decimal:
        return (self.high + self.low + self.close) / Decimal(3)

    @property
    def range_usd(self) -> Decimal:
        return self.high - self.low

    @property
    def green(self) -> bool:
        return self.close > self.open

    @property
    def red(self) -> bool:
        return self.close < self.open
