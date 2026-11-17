"""Immutable session schedule with explicit exchange-local and UTC times."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass(frozen=True, slots=True)
class MarketSession:
    trading_date: date
    open_local: datetime
    close_local: datetime
    early_close: bool = False

    def __post_init__(self) -> None:
        if self.open_local.tzinfo is None or self.close_local.tzinfo is None:
            raise ValueError("session endpoints must be timezone-aware")
        if self.open_local.date() != self.trading_date or self.close_local.date() != self.trading_date:
            raise ValueError("session endpoints must occur on trading date")
        if self.close_local <= self.open_local:
            raise ValueError("session close must be after open")

    @property
    def open_utc(self) -> datetime:
        return self.open_local.astimezone(timezone.utc)

    @property
    def close_utc(self) -> datetime:
        return self.close_local.astimezone(timezone.utc)

    def contains(self, timestamp: datetime, *, include_close: bool = False) -> bool:
        if timestamp.tzinfo is None:
            raise ValueError("timestamp requires timezone")
        return self.open_utc <= timestamp <= self.close_utc if include_close else (
            self.open_utc <= timestamp < self.close_utc)

    @property
    def trading_minutes(self) -> int:
        return int((self.close_utc - self.open_utc).total_seconds() // 60)
