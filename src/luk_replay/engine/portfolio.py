"""Portfolio changes only through validated fills and balanced ledger posts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable

from luk_replay.domain.position import Position
from luk_replay.domain.settings import ReplaySettings
from luk_replay.domain.units import pnl_gbp, to_broker_points

from .fills import EntryFill, ExitFill
from .ledger import Ledger


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    as_of: datetime
    cash_gbp: Decimal
    unrealized_gbp: Decimal
    equity_gbp: Decimal
    open_risk_gbp: Decimal
    open_count: int
    position_ids: tuple[str, ...]


@dataclass(slots=True)
class Portfolio:
    initial_equity_gbp: Decimal
    positions: dict[str, Position] = field(default_factory=dict)
    ledger: Ledger = field(default_factory=Ledger)
    closed: list[Position] = field(default_factory=list)
    exit_fills: list[ExitFill] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.initial_equity_gbp <= 0:
            raise ValueError("initial equity must be positive")

    @property
    def cash_gbp(self) -> Decimal:
        return self.initial_equity_gbp + self.ledger.cash_change()

    @property
    def open_risk_gbp(self) -> Decimal:
        return sum((position.open_risk_gbp for position in self.positions.values()), Decimal())

    def open(self, fill: EntryFill) -> Position:
        if fill.order_id in self.positions or any(
            p.position_id == fill.order_id for p in self.closed
        ):
            raise ValueError("duplicate position identifier")
        position = fill.to_position()
        self.positions[position.position_id] = position
        return position

    def exit(self, fill: ExitFill) -> Position:
        if fill.position_id not in self.positions:
            raise ValueError("exit references an unknown open position")
        existing = self.positions[fill.position_id]
        if fill.volume > existing.open_volume:
            raise ValueError("exit volume exceeds open position")
        expected = pnl_gbp(existing.entry_points, fill.exit_points,
                           Decimal(fill.volume) / 100, existing.side)
        if fill.pnl_gbp != expected:
            raise ValueError("exit P&L does not match entry, price and stake")
        self.ledger.record_exit(fill)
        updated = existing.after_exit(fill.volume, fill.pnl_gbp)
        self.exit_fills.append(fill)
        if updated.open_volume:
            self.positions[fill.position_id] = updated
        else:
            del self.positions[fill.position_id]
            self.closed.append(updated)
        return updated

    def replace(self, updated: Position) -> None:
        existing = self.positions.get(updated.position_id)
        if existing is None:
            raise ValueError("cannot replace closed/absent position")
        if existing.symbol != updated.symbol or existing.open_volume != updated.open_volume:
            raise ValueError("position identity and stake cannot be mutated")
        self.positions[updated.position_id] = updated

    def daily_realized_losses(self, trading_date: date) -> Decimal:
        return -sum((min(fill.pnl_gbp, Decimal()) for fill in self.exit_fills
                     if fill.filled_at.date() == trading_date), Decimal())

    def mark(self, prices_usd: dict[str, Decimal], *, as_of: datetime) -> PortfolioSnapshot:
        if as_of.tzinfo is None:
            raise ValueError("mark requires timezone-aware time")
        unrealized = Decimal()
        for position in self.positions.values():
            if position.symbol not in prices_usd:
                raise ValueError(f"missing price for open position {position.symbol}")
            unrealized += pnl_gbp(position.entry_points,
                                  to_broker_points(prices_usd[position.symbol]),
                                  position.stake_gbp, position.side)
        cash = self.cash_gbp
        return PortfolioSnapshot(as_of, cash, unrealized, cash + unrealized,
                                 self.open_risk_gbp, len(self.positions),
                                 tuple(sorted(self.positions)))

    def verify(self) -> None:
        self.ledger.verify()
        if self.cash_gbp != self.initial_equity_gbp + sum(
            (fill.pnl_gbp for fill in self.exit_fills), Decimal()
        ):
            raise ValueError("portfolio cash does not reconcile to exit fills")
        for position in self.positions.values():
            if position.open_volume <= 0:
                raise ValueError("closed position retained in open book")
