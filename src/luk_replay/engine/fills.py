"""Deterministic conservative OHLC fills, spread, gaps and slippage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from luk_replay.domain.bar import Bar
from luk_replay.domain.order import OrderIntent, OrderSide, OrderStatus, OrderType
from luk_replay.domain.position import Position
from luk_replay.domain.units import pnl_gbp, stake_for_volume, to_broker_points
from luk_replay.strategy.reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class Quote:
    bid_points: Decimal
    ask_points: Decimal
    mid_points: Decimal
    as_of: datetime
    assumed: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.bid_points <= self.mid_points <= self.ask_points:
            raise ValueError("quote must have positive bid <= mid <= ask")
        if self.as_of.tzinfo is None:
            raise ValueError("quote timestamp requires timezone")

    @property
    def spread_points(self) -> Decimal:
        return self.ask_points - self.bid_points

    @property
    def spread_pct(self) -> Decimal:
        return self.spread_points / self.mid_points * Decimal(100)


def assumed_quote(usd: Decimal, *, spread_pct: Decimal, as_of: datetime) -> Quote:
    if spread_pct < 0:
        raise ValueError("spread cannot be negative")
    mid = to_broker_points(usd)
    half = (mid * spread_pct / Decimal(200)).quantize(Decimal("0.0001"))
    return Quote(mid - half, mid + half, mid, as_of)


@dataclass(frozen=True, slots=True)
class EntryFill:
    order_id: str
    symbol: str
    filled_at: datetime
    entry_points: Decimal
    volume: int
    quote_assumed: bool
    protective_stop_points: Decimal | None
    side: str = "LONG"

    def to_position(self) -> Position:
        if self.protective_stop_points is None:
            raise ValueError("simulated entries require protective stop")
        return Position(self.order_id, self.symbol, self.side, self.filled_at,
                        self.entry_points, self.protective_stop_points, self.volume)


@dataclass(frozen=True, slots=True)
class ExitFill:
    position_id: str
    symbol: str
    filled_at: datetime
    exit_points: Decimal
    volume: int
    pnl_gbp: Decimal
    reason: str
    quote_assumed: bool = True

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("an exit needs its cause")
        stake_for_volume(self.volume)


def entry_on_bar(order: OrderIntent, bar: Bar, *, spread_pct: Decimal,
                 slippage_points: Decimal = Decimal()) -> EntryFill | None:
    if order.status != OrderStatus.PENDING or bar.symbol != order.symbol:
        return None
    if order.submitted_at > bar.timestamp:
        return None
    if slippage_points < 0:
        raise ValueError("slippage cannot improve an entry")
    if order.kind == OrderType.MARKET:
        chosen = bar.open
    elif order.kind == OrderType.LIMIT:
        if order.target_points is None:
            return None
        trigger_usd = order.target_points / 100
        if order.side == OrderSide.LONG and bar.low > trigger_usd:
            return None
        if order.side == OrderSide.SHORT and bar.high < trigger_usd:
            return None
        chosen = min(bar.open, trigger_usd) if order.side == OrderSide.LONG else max(bar.open, trigger_usd)
    else:
        if order.target_points is None:
            return None
        trigger_usd = order.target_points / 100
        if order.side == OrderSide.LONG and bar.high < trigger_usd:
            return None
        if order.side == OrderSide.SHORT and bar.low > trigger_usd:
            return None
        chosen = max(bar.open, trigger_usd) if order.side == OrderSide.LONG else min(bar.open, trigger_usd)
    quote = assumed_quote(chosen, spread_pct=spread_pct, as_of=bar.timestamp)
    points = (quote.ask_points + slippage_points if order.side == OrderSide.LONG
              else quote.bid_points - slippage_points)
    return EntryFill(order.order_id, bar.symbol, bar.timestamp, points,
                     order.volume, quote.assumed, order.protective_stop_points,
                     order.side.value)


def exit_on_bar(position: Position, bar: Bar, *, spread_pct: Decimal,
                slippage_points: Decimal = Decimal(),
                conservative_same_bar: bool = True) -> ExitFill | None:
    if position.open_volume == 0 or position.symbol != bar.symbol:
        return None
    if bar.timestamp < position.opened_at:
        return None
    if slippage_points < 0:
        raise ValueError("slippage cannot improve an exit")
    stop_usd = position.stop_points / 100
    target_usd = position.target_points / 100 if position.target_points else None
    if position.side == "LONG":
        gap = bar.open <= stop_usd
        touched_stop = bar.low <= stop_usd
        touched_target = target_usd is not None and bar.high >= target_usd
        if not touched_stop and not touched_target:
            return None
        if touched_stop and (conservative_same_bar or not touched_target):
            chosen = bar.open if gap else stop_usd
            reason = ReasonCode.GAP_THROUGH_STOP if gap else ReasonCode.STOP_FILLED
        else:
            chosen, reason = max(bar.open, target_usd), ReasonCode.TARGET_FILLED
        quote = assumed_quote(chosen, spread_pct=spread_pct,
                              as_of=bar.timestamp if gap else bar.end_time)
        actual = quote.bid_points - slippage_points
    else:
        gap = bar.open >= stop_usd
        touched_stop = bar.high >= stop_usd
        touched_target = target_usd is not None and bar.low <= target_usd
        if not touched_stop and not touched_target:
            return None
        if touched_stop and (conservative_same_bar or not touched_target):
            chosen = bar.open if gap else stop_usd
            reason = ReasonCode.GAP_THROUGH_STOP if gap else ReasonCode.STOP_FILLED
        else:
            chosen, reason = min(bar.open, target_usd), ReasonCode.TARGET_FILLED
        quote = assumed_quote(chosen, spread_pct=spread_pct,
                              as_of=bar.timestamp if gap else bar.end_time)
        actual = quote.ask_points + slippage_points
    return ExitFill(position.position_id, position.symbol, quote.as_of,
                    actual, position.open_volume,
                    pnl_gbp(position.entry_points, actual, position.stake_gbp, position.side),
                    reason.value, quote.assumed)
