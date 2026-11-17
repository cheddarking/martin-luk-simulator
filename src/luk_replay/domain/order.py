"""Explicit order intent and state without an actual broker connection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .units import risk_gbp, stake_for_volume


class OrderSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    order_id: str
    symbol: str
    side: OrderSide
    kind: OrderType
    submitted_at: datetime
    volume: int
    target_points: Decimal | None = None
    protective_stop_points: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING

    def __post_init__(self) -> None:
        if not self.order_id or not self.symbol:
            raise ValueError("order id and symbol are required")
        if self.submitted_at.tzinfo is None:
            raise ValueError("order time requires timezone")
        stake_for_volume(self.volume)
        if self.kind != OrderType.MARKET and self.target_points is None:
            raise ValueError("limit/stop order requires a trigger")
        if self.target_points is not None and self.target_points <= 0:
            raise ValueError("trigger must be positive")

    def with_status(self, status: OrderStatus) -> "OrderIntent":
        if self.status != OrderStatus.PENDING:
            raise ValueError("only pending orders may transition")
        if status == OrderStatus.PENDING:
            return self
        return replace(self, status=status)

    def estimated_risk(self, entry_points: Decimal) -> Decimal | None:
        if self.protective_stop_points is None:
            return None
        return risk_gbp(entry_points, self.protective_stop_points,
                        stake_for_volume(self.volume))
