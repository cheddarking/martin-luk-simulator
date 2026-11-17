"""Deterministic pending-order queue with idempotent state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from luk_replay.domain.bar import Bar
from luk_replay.domain.order import OrderIntent, OrderStatus

from .fills import EntryFill, entry_on_bar


@dataclass(slots=True)
class OrderBook:
    pending: dict[str, OrderIntent] = field(default_factory=dict)
    terminal: dict[str, OrderIntent] = field(default_factory=dict)

    def submit(self, intent: OrderIntent) -> None:
        if intent.status != OrderStatus.PENDING:
            raise ValueError("only pending orders can be submitted")
        if intent.order_id in self.pending or intent.order_id in self.terminal:
            raise ValueError("duplicate order identifier")
        self.pending[intent.order_id] = intent

    def cancel(self, order_id: str) -> OrderIntent:
        original = self.pending.pop(order_id)
        cancelled = original.with_status(OrderStatus.CANCELLED)
        self.terminal[order_id] = cancelled
        return cancelled

    def expire_before(self, timestamp: datetime) -> tuple[OrderIntent, ...]:
        expired = tuple(order for order in self.pending.values()
                        if order.submitted_at.date() < timestamp.date())
        return tuple(self.cancel(order.order_id) for order in expired)

    def fill(self, bar: Bar, *, spread_pct: Decimal,
             slippage_points: Decimal = Decimal()) -> tuple[EntryFill, ...]:
        results: list[EntryFill] = []
        for order in tuple(self.pending.values()):
            result = entry_on_bar(order, bar, spread_pct=spread_pct,
                                  slippage_points=slippage_points)
            if result is None:
                continue
            del self.pending[order.order_id]
            self.terminal[order.order_id] = order.with_status(OrderStatus.FILLED)
            results.append(result)
        return tuple(results)

    def reject_quoted_fill(self, order_id: str) -> OrderIntent:
        """Undo a provisional quote when the actual fill fails risk checks."""
        provisional = self.terminal[order_id]
        if provisional.status != OrderStatus.FILLED:
            raise ValueError("only a provisional filled quote can be rejected")
        rejected = replace(provisional, status=OrderStatus.REJECTED)
        self.terminal[order_id] = rejected
        return rejected

    def count_for(self, symbol: str) -> int:
        return sum(order.symbol == symbol for order in self.pending.values())
