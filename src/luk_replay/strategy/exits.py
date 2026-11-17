"""End-of-day trail and R-multiple trims from observations known as-of."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Sequence

from luk_replay.domain.bar import Bar
from luk_replay.domain.position import Position
from luk_replay.domain.session import MarketSession
from luk_replay.domain.units import pnl_gbp
from luk_replay.engine.fills import ExitFill, assumed_quote
from luk_replay.market.asof import MarketView
from luk_replay.market.indicators import ema_series

from .reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class TrailDecision:
    position_id: str
    as_of: datetime
    reason: str
    exit_now: bool
    armed: bool
    ema_points: Decimal | None
    observed_close_points: Decimal | None
    note: str


def evaluate_ema_trail(position: Position, market: MarketView,
                       *, as_of: datetime, cushion_r: Decimal = Decimal()) -> TrailDecision:
    if as_of.tzinfo is None:
        raise ValueError("trail decision time requires timezone")
    if position.symbol != market.symbol or as_of != market.as_of:
        raise ValueError("trail market view must match position and evaluation time")
    if not market.daily:
        return TrailDecision(position.position_id, as_of, ReasonCode.INSUFFICIENT_HISTORY.value,
                             False, position.ema_trail_armed, None, None,
                             "no completed daily bar is available")
    latest = market.daily[-1]
    if latest.timestamp.date() == position.opened_at.date():
        return TrailDecision(position.position_id, as_of,
                             ReasonCode.ENTRY_DAY_TRAIL_SKIPPED.value, False,
                             position.ema_trail_armed, None, None,
                             "entry-day daily EMA exits are disabled")
    period = 21 if cushion_r >= Decimal(4) else 9
    if len(market.daily) < period:
        return TrailDecision(position.position_id, as_of,
                             ReasonCode.INSUFFICIENT_HISTORY.value, False,
                             position.ema_trail_armed, None, None,
                             f"needs {period} completed daily bars")
    ema = (ema_series(market.daily, period)[-1] * 100)
    close = latest.close * 100
    favorable = close > ema if position.side == "LONG" else close < ema
    if favorable:
        return TrailDecision(position.position_id, as_of, "TRAIL_ARMED", False,
                             True, ema, close,
                             f"completed daily close holds {'above' if position.side == 'LONG' else 'below'} EMA{period}")
    if not position.ema_trail_armed:
        return TrailDecision(position.position_id, as_of, "TRAIL_NOT_ARMED", False,
                             False, ema, close,
                             "no favorable completed daily close since entry")
    return TrailDecision(position.position_id, as_of, ReasonCode.EOD_EMA_EXIT.value,
                         True, True, ema, close, f"completed daily close crossed EMA{period}")


def apply_trail_arm(position: Position, decision: TrailDecision) -> Position:
    if decision.position_id != position.position_id:
        raise ValueError("trail decision targets a different position")
    return replace(position, ema_trail_armed=decision.armed)


def partial_target_fills(
    position: Position, bar: Bar, *, spread_pct: Decimal,
    slippage_points: Decimal = Decimal(),
) -> tuple[ExitFill, ...]:
    """Express 15% trims at +3R and +5R only when broker stake steps allow.

    If a stop is touched in this bar, the intrabar order is unknown: the stop
    takes precedence and this helper leaves the full close to the caller.
    """
    if bar.symbol != position.symbol or bar.timestamp < position.opened_at:
        return ()
    if slippage_points < 0:
        raise ValueError("slippage cannot improve an exit")
    if position.side == "LONG" and bar.low * 100 <= position.stop_points:
        return ()
    if position.side == "SHORT" and bar.high * 100 >= position.stop_points:
        return ()
    initial_r = abs(position.entry_points - position.stop_points)
    remaining = position.open_volume
    fills: list[ExitFill] = []
    for multiple in (3, 5):
        if multiple in position.trimmed_targets:
            continue
        raw_target = (position.entry_points + initial_r * multiple if position.side == "LONG"
                      else position.entry_points - initial_r * multiple)
        target = raw_target.to_integral_value(
            rounding=ROUND_CEILING if position.side == "LONG" else ROUND_FLOOR)
        touched = bar.high * 100 >= target if position.side == "LONG" else (
            bar.low * 100 <= target)
        if not touched:
            continue
        # The 15% fraction is expressed in available volume at this point.
        requested = int((Decimal(remaining) * Decimal("0.15") / 10)
                        .to_integral_value(rounding=ROUND_FLOOR)) * 10
        if requested < 10 or remaining - requested < 10:
            continue
        first_price = bar.open * 100
        chosen = max(first_price, target) if position.side == "LONG" else min(first_price, target)
        quote = assumed_quote(chosen / 100, spread_pct=spread_pct, as_of=bar.end_time)
        filled_points = quote.bid_points - slippage_points if position.side == "LONG" else (
            quote.ask_points + slippage_points)
        stake = Decimal(requested) / 100
        fills.append(ExitFill(position.position_id, position.symbol, bar.end_time,
                              filled_points, requested,
                              pnl_gbp(position.entry_points, filled_points, stake, position.side),
                              f"TRIM_{multiple}R", quote.assumed))
        remaining -= requested
    return tuple(fills)


def evaluate_forming_ema_trail(
    position: Position, daily: Sequence[Bar], intraday: Sequence[Bar], *,
    as_of: datetime, session: MarketSession,
) -> TrailDecision:
    """Evaluate at the scheduled pre-close from completed intraday bars only.

    Yesterday's daily bars must already be complete; today's *forming* close is
    reconstructed from minute bars whose end_time <= as_of. No final bar, high
    or low beyond as_of enters the trail.
    """
    if as_of.tzinfo is None or session.trading_date != as_of.date():
        raise ValueError("trail time must be an aware session-local timestamp")
    if as_of < session.close_local - timedelta(minutes=10) or as_of > session.close_local:
        raise ValueError("forming daily trail is valid only in the closing window")
    if position.opened_at.date() == session.trading_date:
        return TrailDecision(position.position_id, as_of,
                             ReasonCode.ENTRY_DAY_TRAIL_SKIPPED.value,
                             False, position.ema_trail_armed, None, None,
                             "today's new position is not EMA-exited")
    prior = tuple(bar for bar in daily if bar.symbol == position.symbol
                  and bar.timestamp.date() < session.trading_date
                  and bar.end_time <= as_of)
    today = tuple(bar for bar in intraday if bar.symbol == position.symbol
                  and bar.timestamp.date() == session.trading_date
                  and bar.end_time <= as_of)
    if len(prior) < 21 or not today:
        return TrailDecision(position.position_id, as_of,
                             ReasonCode.INSUFFICIENT_HISTORY.value, False,
                             position.ema_trail_armed, None, None,
                             "requires 21 completed prior daily bars and a current completed minute bar")
    last_close = today[-1].close
    period = 9
    # A runner cushioned by at least +4R gets the 21 EMA.
    gain = ((last_close * 100 - position.entry_points) if position.side == "LONG"
            else (position.entry_points - last_close * 100))
    if gain >= abs(position.entry_points - position.stop_points) * 4:
        period = 21
    previous_series = ema_series(prior, period)
    previous_ema = previous_series[-1]
    alpha = Decimal(2) / Decimal(period + 1)
    forming_ema = (previous_ema + alpha * (last_close - previous_ema)) * 100
    close_points = last_close * 100
    favorable = close_points > forming_ema if position.side == "LONG" else (
        close_points < forming_ema)
    # A provisional 15:55 close can trigger an already-armed exit but must not
    # arm it: arming requires a *completed* daily close after the entry date.
    completed_favorable = any(
        bar.timestamp.date() > position.opened_at.date() and
        (bar.close > average if position.side == "LONG" else bar.close < average)
        for bar, average in zip(prior, previous_series)
    )
    armed = position.ema_trail_armed or completed_favorable
    if favorable:
        return TrailDecision(position.position_id, as_of,
                             "TRAIL_HOLD" if armed else "TRAIL_NOT_ARMED", False,
                             armed, forming_ema, close_points,
                             f"as-of forming close holds favorable side of EMA{period}")
    if not armed:
        return TrailDecision(position.position_id, as_of, "TRAIL_NOT_ARMED", False,
                             False, forming_ema, close_points,
                             "no previous favorable completed daily close has armed the trail")
    return TrailDecision(position.position_id, as_of, ReasonCode.EOD_EMA_EXIT.value,
                         True, True, forming_ema, close_points,
                         f"as-of forming close crossed EMA{period}")
