"""Spread-bet instrument properties, independent of any broker connection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .units import MIN_VOLUME, STEP_VOLUME, stake_for_volume, to_broker_points


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    currency: str = "USD"
    broker_suffix: str = ".US_SB"
    min_volume: int = MIN_VOLUME
    step_volume: int = STEP_VOLUME
    max_spread_pct: Decimal = Decimal("0.25")

    def __post_init__(self) -> None:
        if not self.symbol or any(char.isspace() for char in self.symbol):
            raise ValueError("instrument symbol is required")
        if self.currency != "USD":
            raise ValueError("this simulator supports only USD-quoted US equities")
        if self.min_volume < 10 or self.step_volume < 1:
            raise ValueError("invalid stake specification")
        if self.max_spread_pct < 0:
            raise ValueError("max spread must be non-negative")

    @property
    def broker_symbol(self) -> str:
        return f"{self.symbol}{self.broker_suffix}"

    def stake(self, volume: int) -> Decimal:
        if volume < self.min_volume or volume % self.step_volume:
            raise ValueError("volume does not meet instrument minimum or step")
        return stake_for_volume(volume)

    def quote(self, usd: Decimal) -> Decimal:
        return to_broker_points(usd)
