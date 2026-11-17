"""Daily swing replay: completed session evidence, next-open execution.

No decision is attributed to an invented 15:55 minute in a D1-only dataset.
The open and complete OHLCV of a day are distinct observation phases.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from luk_replay.domain.bar import Bar
from luk_replay.domain.events import Decision, EventKind, ReplayEvent
from luk_replay.domain.order import OrderIntent, OrderSide, OrderType
from luk_replay.domain.settings import ReplaySettings, RiskSettings
from luk_replay.domain.units import pnl_gbp
from luk_replay.ingest.daily_csv import DailyHistory
from luk_replay.market.indicators import ema_series
from luk_replay.strategy.context import build_daily_context
from luk_replay.strategy.exits import partial_target_fills
from luk_replay.strategy.reasons import ReasonCode, explain
from luk_replay.strategy.risk import assess_risk
from luk_replay.strategy.setups import evaluate_pullback

from .fills import EntryFill, ExitFill, assumed_quote, exit_on_bar
from .orders import OrderBook
from .portfolio import Portfolio
from .replay import ReplayResult

DAILY_VERSION = "daily-swing-v1"


def _valid_fill(fill: EntryFill, limit: RiskSettings, portfolio: Portfolio) -> tuple[ReasonCode | None, Decimal]:
    stop = fill.protective_stop_points
    if stop is None or (fill.side == "LONG" and fill.entry_points <= stop) or (
        fill.side == "SHORT" and fill.entry_points >= stop
    ):
        return ReasonCode.STOP_INVALID_SIDE, Decimal()
    risk = abs(fill.entry_points - stop) * Decimal(fill.volume) / 100
    budget = limit.equity_gbp * limit.risk_pct / 100
    if risk > budget * Decimal("1.25"):
        return ReasonCode.GAP_RISK_EXCEEDED, risk
    if risk + portfolio.open_risk_gbp > limit.equity_gbp * limit.max_open_risk_pct / 100:
        return ReasonCode.OPEN_RISK_CAP, risk
    notional = fill.entry_points * Decimal(fill.volume) / 100
    if notional > limit.equity_gbp * limit.large_cap_max_notional_pct / 100:
        return ReasonCode.NOTIONAL_CAP, risk
    return None, risk


def _trail_on_completed_daily(position, history: tuple[Bar, ...]) -> tuple[str, bool]:
    """Return (reason, schedule-next-open-exit); arm only after a real close."""
    current = history[-1]
    if current.timestamp.date() <= position.opened_at.date():
        return ReasonCode.ENTRY_DAY_TRAIL_SKIPPED.value, False
    gained = current.close * 100 - position.entry_points
    base_risk = abs(position.entry_points - position.stop_points)
    period = 21 if gained >= base_risk * 4 else 9
    if len(history) < period:
        return ReasonCode.INSUFFICIENT_HISTORY.value, False
    level = ema_series(history, period)[-1]
    if current.close > level:
        return "TRAIL_ARMED", False
    if position.ema_trail_armed:
        return ReasonCode.EOD_EMA_EXIT.value, True
    return "TRAIL_NOT_ARMED", False


def replay_daily(
    history: DailyHistory, *, start_date: date | None = None,
    end_date: date | None = None,
    settings: ReplaySettings | None = None, risk_settings: RiskSettings | None = None,
) -> ReplayResult:
    """Replay a single actual daily series under a declared execution model.

    Pre-start bars warm the indicators but never become trading signals. Every
    day's high/low is evaluated only after that day's close; the actual intraday
    order is unknowable, so a stop wins ambiguous same-day outcomes.
    """
    if not history.bars:
        raise ValueError("daily replay needs at least one bar")
    config = settings or ReplaySettings(strategy_version=DAILY_VERSION)
    if config.strategy_version != DAILY_VERSION:
        config = replace(config, strategy_version=DAILY_VERSION)
    limit = risk_settings or RiskSettings(equity_gbp=config.initial_equity_gbp)
    start = start_date or history.first_date
    end = end_date or history.last_date
    if start > end:
        raise ValueError("daily replay start must not exceed end")
    book = OrderBook()
    portfolio = Portfolio(config.initial_equity_gbp)
    events: list[ReplayEvent] = []
    decisions: list[Decision] = []
    entries: list[EntryFill] = []
    exits: list[ExitFill] = []
    snapshots = []
    known: list[Bar] = []
    pending_ema_exits: set[str] = set()
    symbol = history.symbol

    def add(at: datetime, kind: EventKind, reason: str,
            details: dict[str, str] | None = None) -> None:
        events.append(ReplayEvent(len(events), at, kind, symbol, reason,
                                  details or {}, DAILY_VERSION))

    def close_position(position, fill: ExitFill, *, event_time: datetime) -> None:
        portfolio.exit(fill)
        exits.append(fill)
        add(event_time, EventKind.EXIT, fill.reason,
            {"fill_points": str(fill.exit_points), "pnl_gbp": str(fill.pnl_gbp),
             "bar_resolution": "daily", "quote_assumed": str(fill.quote_assumed)})

    for bar in history.bars:
        day = bar.timestamp.date()
        if day > end:
            break
        if day < start:
            known.append(bar)
            continue
        # OPEN phase: neither today's high/low nor today's close is available.
        for position in tuple(portfolio.positions.values()):
            if position.position_id in pending_ema_exits:
                quote = assumed_quote(bar.open, spread_pct=config.default_spread_pct,
                                      as_of=bar.timestamp)
                price = quote.bid_points if position.side == "LONG" else quote.ask_points
                fill = ExitFill(position.position_id, symbol, bar.timestamp, price,
                                position.open_volume,
                                pnl_gbp(position.entry_points, price,
                                        position.stake_gbp, position.side),
                                ReasonCode.EOD_EMA_EXIT.value, quote.assumed)
                close_position(position, fill, event_time=bar.timestamp)
                pending_ema_exits.remove(position.position_id)
                continue
            stop_crossed = (bar.open * 100 <= position.stop_points if position.side == "LONG"
                            else bar.open * 100 >= position.stop_points)
            if stop_crossed:
                fill = exit_on_bar(position, bar,
                                   spread_pct=config.default_spread_pct,
                                   slippage_points=config.slippage_points)
                if fill is not None:
                    close_position(position, fill, event_time=bar.timestamp)
        # Daily orders submitted at yesterday's close remain pending across
        # weekends and holidays until the next available exchange open.
        for fill in book.fill(bar, spread_pct=config.default_spread_pct,
                              slippage_points=config.slippage_points):
            reason, risk = _valid_fill(fill, limit, portfolio)
            if reason is not None:
                book.reject_quoted_fill(fill.order_id)
                add(bar.timestamp, EventKind.REJECTION, reason.value,
                    {"quoted_entry_points": str(fill.entry_points),
                     "actual_risk_gbp": str(risk), "note": explain(reason)})
                continue
            portfolio.open(fill)
            entries.append(fill)
            add(bar.timestamp, EventKind.ORDER_FILLED, "ENTRY_FILLED",
                {"price_points": str(fill.entry_points), "volume": str(fill.volume),
                 "risk_gbp": str(risk), "quote_assumed": str(fill.quote_assumed)})
        # CLOSE phase: the full day's OHLC and volume are now observable.
        known.append(bar)
        add(bar.end_time, EventKind.BAR_COMPLETED, "DAILY_BAR_COMPLETED",
            {"date": day.isoformat(), "close_usd": str(bar.close),
             "source": history.source_kind, "adjustment": history.adjustment})
        for position in tuple(portfolio.positions.values()):
            fill = exit_on_bar(position, bar,
                               spread_pct=config.default_spread_pct,
                               slippage_points=config.slippage_points,
                               conservative_same_bar=True)
            if fill is not None:
                close_position(position, fill, event_time=bar.end_time)
                pending_ema_exits.discard(position.position_id)
                continue
            for trim in partial_target_fills(position, bar,
                                             spread_pct=config.default_spread_pct,
                                             slippage_points=config.slippage_points):
                portfolio.exit(trim)
                exits.append(trim)
                level = 3 if trim.reason == "TRIM_3R" else 5
                portfolio.replace(portfolio.positions[position.position_id].mark_trim(level))
                add(bar.end_time, EventKind.TRIM, trim.reason,
                    {"volume": str(trim.volume), "pnl_gbp": str(trim.pnl_gbp)})
            current = portfolio.positions.get(position.position_id)
            if current is None or current.position_id in pending_ema_exits:
                continue
            trail_reason, schedule_exit = _trail_on_completed_daily(current, tuple(known))
            add(bar.end_time, EventKind.RISK, trail_reason,
                {"execution": "next_open" if schedule_exit else "none"})
            if schedule_exit:
                pending_ema_exits.add(current.position_id)
            elif trail_reason == "TRAIL_ARMED" and not current.ema_trail_armed:
                portfolio.replace(replace(current, ema_trail_armed=True))
        context = build_daily_context(known, support_lookback=5)
        decision = evaluate_pullback(context, as_of=bar.end_time, price_usd=bar.close)
        decision = replace(decision, strategy_version=DAILY_VERSION)
        if portfolio.positions or book.pending or pending_ema_exits:
            decision = replace(decision, accepted=False,
                               reason=ReasonCode.DUPLICATE_SIGNAL.value,
                               description="An existing position or order blocks a new daily entry")
        if decision.accepted and context is not None and context.zone is not None:
            stop_usd = context.zone.low - Decimal("0.01")
            assessed = assess_risk(
                entry_usd=bar.close, stop_usd=stop_usd,
                as_of=bar.end_time, settings=limit, strategy_version=DAILY_VERSION,
                spread_pct=config.default_spread_pct,
                open_risk_gbp=portfolio.open_risk_gbp,
                realized_loss_today_gbp=portfolio.daily_realized_losses(day),
                open_positions=len(portfolio.positions), adr_usd=context.adr,
            )
            if assessed.allowed:
                book.submit(OrderIntent(
                    f"daily:{symbol}:{day.isoformat()}", symbol, OrderSide.LONG,
                    OrderType.MARKET, bar.end_time, assessed.volume,
                    protective_stop_points=assessed.stop_points,
                ))
                add(bar.end_time, EventKind.ORDER_SUBMITTED, "RISK_APPROVED",
                    {"budget_gbp": str(assessed.budget_gbp),
                     "reserved_gbp": str(assessed.risk_gbp),
                     "first_fill_time": "next_session_open"})
            else:
                decision = replace(decision, accepted=False,
                                   reason=assessed.reason.value,
                                   description=assessed.detail or explain(assessed.reason))
        decisions.append(decision)
        events.append(decision.as_event(len(events)))
        snapshots.append(portfolio.mark({symbol: bar.close}, as_of=bar.end_time))
    portfolio.verify()
    final = snapshots[-1].equity_gbp if snapshots else config.initial_equity_gbp
    return ReplayResult(symbol, DAILY_VERSION, history.sha256, tuple(events),
                        tuple(decisions), tuple(entries), tuple(exits), tuple(snapshots),
                        config.initial_equity_gbp, final, len(portfolio.positions),
                        portfolio.cash_gbp, source_kind=history.source_kind,
                        adjustment=history.adjustment, timeframe="daily",
                        first_date=start.isoformat(), last_date=end.isoformat())
