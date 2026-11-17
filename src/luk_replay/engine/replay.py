"""Pure deterministic replay over a chronological offline bar sequence.

Only information available by each bar's completion is used to make decisions;
orders submitted on that close cannot fill until a subsequent bar opens.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Sequence

from luk_replay.domain.bar import Bar
from luk_replay.domain.events import Decision, EventKind, ReplayEvent
from luk_replay.domain.order import OrderIntent, OrderSide, OrderType
from luk_replay.domain.settings import ReplaySettings, RiskSettings
from luk_replay.domain.units import pnl_gbp, to_broker_points
from luk_replay.market.asof import bars_known_at
from luk_replay.market.calendar import USMarketCalendar
from luk_replay.strategy.context import build_daily_context
from luk_replay.strategy.exits import (apply_trail_arm, evaluate_forming_ema_trail,
                                       partial_target_fills)
from luk_replay.strategy.reasons import ReasonCode
from luk_replay.strategy.risk import assess_risk
from luk_replay.strategy.setups import evaluate_pullback

from .fills import EntryFill, ExitFill, assumed_quote, exit_on_bar
from .orders import OrderBook
from .portfolio import Portfolio, PortfolioSnapshot
from .timeline import market_ticks, validate_timeline


@dataclass(frozen=True, slots=True)
class ReplayResult:
    symbol: str
    strategy_version: str
    source_digest: str
    events: tuple[ReplayEvent, ...]
    decisions: tuple[Decision, ...]
    entries: tuple[EntryFill, ...]
    exits: tuple[ExitFill, ...]
    snapshots: tuple[PortfolioSnapshot, ...]
    initial_equity_gbp: Decimal
    final_equity_gbp: Decimal
    open_count: int
    ending_cash_gbp: Decimal
    source_kind: str = "synthetic"
    adjustment: str = "unknown"
    timeframe: str = "minute"
    first_date: str | None = None
    last_date: str | None = None

    @property
    def accepted_count(self) -> int:
        return sum(decision.accepted for decision in self.decisions)

    @property
    def rejected_count(self) -> int:
        return sum(not decision.accepted for decision in self.decisions)

    @property
    def net_pnl_gbp(self) -> Decimal:
        return self.final_equity_gbp - self.initial_equity_gbp

    def reason_counts(self) -> dict[str, int]:
        output: dict[str, int] = {}
        for decision in self.decisions:
            output[decision.reason] = output.get(decision.reason, 0) + 1
        return dict(sorted(output.items()))


def replay(
    intraday: Sequence[Bar], *, daily: Sequence[Bar] = (),
    settings: ReplaySettings | None = None, risk_settings: RiskSettings | None = None,
    calendar: USMarketCalendar | None = None, source_digest: str = "synthetic",
) -> ReplayResult:
    """Run a single symbol through a bar-close setup and next-open fill cycle.

    When no daily lookback is supplied, decisions are correctly rejected for
    insufficient history rather than manufactured from future intraday bars.
    """
    if not intraday:
        raise ValueError("replay needs at least one intraday bar")
    if any(bar.symbol != intraday[0].symbol for bar in (*intraday, *daily)):
        raise ValueError("replay accepts one symbol at a time")
    if any(bar.timeframe_seconds >= 3600 for bar in intraday):
        raise ValueError("intraday replay input must be shorter than one hour")
    config = settings or ReplaySettings()
    limit = risk_settings or RiskSettings(equity_gbp=config.initial_equity_gbp)
    schedule = calendar or USMarketCalendar()
    book = OrderBook()
    portfolio = Portfolio(config.initial_equity_gbp)
    decisions: list[Decision] = []
    events: list[ReplayEvent] = []
    entries: list[EntryFill] = []
    exits: list[ExitFill] = []
    snapshots: list[PortfolioSnapshot] = []
    last_price: dict[str, Decimal] = {}
    submitted_dates: set[tuple[str, str]] = set()
    evaluated_trails: set[tuple[str, str]] = set()
    ticks = market_ticks(intraday)
    validate_timeline(ticks)
    symbol = intraday[0].symbol

    def event(at: datetime, kind: EventKind, reason: str,
              details: dict[str, str] | None = None) -> None:
        events.append(ReplayEvent(len(events), at, kind, symbol, reason,
                                  details or {}, config.strategy_version))

    for tick in ticks:
        bar = tick.bar
        if tick.phase == "OPEN":
            if not schedule.is_open(bar.timestamp.date()):
                event(tick.at, EventKind.REJECTION, ReasonCode.MARKET_CLOSED.value)
                continue
            session = schedule.session(bar.timestamp.date())
            if not session.contains(tick.at):
                event(tick.at, EventKind.REJECTION, ReasonCode.NOT_IN_SESSION.value)
                continue
            book.expire_before(tick.at)
            for position in tuple(portfolio.positions.values()):
                # At the open only the open price is observable; intrabar highs
                # and lows must wait until this bar is complete.
                gapped = (bar.open * 100 <= position.stop_points if position.side == "LONG"
                          else bar.open * 100 >= position.stop_points)
                if not gapped:
                    continue
                exit_fill = exit_on_bar(
                    position, bar, spread_pct=config.default_spread_pct,
                    slippage_points=config.slippage_points,
                    conservative_same_bar=config.conservative_same_bar,
                )
                if exit_fill is not None:
                    portfolio.exit(exit_fill)
                    exits.append(exit_fill)
                    event(tick.at, EventKind.EXIT, exit_fill.reason,
                          {"points": str(exit_fill.exit_points),
                           "pnl_gbp": str(exit_fill.pnl_gbp)})
            for entry in book.fill(bar, spread_pct=config.default_spread_pct,
                                   slippage_points=config.slippage_points):
                # A quoted next-open gap is not yet an accepted fill. A fixed
                # broker stake must still be protective and within *both* risk
                # limits at its actual opening price before the portfolio opens.
                stop = entry.protective_stop_points
                protective = stop is not None and (
                    entry.entry_points > stop if entry.side == "LONG"
                    else entry.entry_points < stop)
                if not protective:
                    book.reject_quoted_fill(entry.order_id)
                    event(tick.at, EventKind.REJECTION,
                          ReasonCode.STOP_INVALID_SIDE.value,
                          {"entry_points": str(entry.entry_points),
                           "stop_points": str(stop or "")})
                    continue
                filled_risk = abs(entry.entry_points - stop) * Decimal(entry.volume) / 100
                trade_budget = limit.equity_gbp * limit.risk_pct / 100
                if filled_risk > trade_budget * Decimal("1.25"):
                    book.reject_quoted_fill(entry.order_id)
                    event(tick.at, EventKind.REJECTION,
                          ReasonCode.GAP_RISK_EXCEEDED.value,
                          {"filled_risk_gbp": str(filled_risk),
                           "budget_gbp": str(trade_budget)})
                    continue
                if (portfolio.open_risk_gbp + filled_risk >
                        limit.equity_gbp * limit.max_open_risk_pct / 100):
                    book.reject_quoted_fill(entry.order_id)
                    event(tick.at, EventKind.REJECTION, ReasonCode.OPEN_RISK_CAP.value,
                          {"filled_risk_gbp": str(filled_risk)})
                    continue
                filled_notional = entry.entry_points * Decimal(entry.volume) / 100
                if (filled_notional > limit.equity_gbp *
                        limit.large_cap_max_notional_pct / 100):
                    book.reject_quoted_fill(entry.order_id)
                    event(tick.at, EventKind.REJECTION, ReasonCode.NOTIONAL_CAP.value,
                          {"filled_notional_gbp": str(filled_notional)})
                    continue
                portfolio.open(entry)
                entries.append(entry)
                event(tick.at, EventKind.ORDER_FILLED, "ENTRY_FILLED",
                      {"points": str(entry.entry_points),
                       "volume": str(entry.volume)})
        else:
            if not schedule.is_open(bar.timestamp.date()):
                continue
            session = schedule.session(bar.timestamp.date())
            if bar.end_time > session.close_local:
                continue
            last_price[symbol] = bar.close
            event(tick.at, EventKind.BAR_COMPLETED, "BAR_COMPLETED",
                  {"close_usd": str(bar.close)})
            for position in tuple(portfolio.positions.values()):
                exit_fill = exit_on_bar(
                    position, bar, spread_pct=config.default_spread_pct,
                    slippage_points=config.slippage_points,
                    conservative_same_bar=config.conservative_same_bar,
                )
                if exit_fill is not None:
                    portfolio.exit(exit_fill)
                    exits.append(exit_fill)
                    event(tick.at, EventKind.EXIT, exit_fill.reason,
                          {"points": str(exit_fill.exit_points),
                           "pnl_gbp": str(exit_fill.pnl_gbp)})
            for position in tuple(portfolio.positions.values()):
                # Protective stop has priority over targets in an ambiguous bar.
                if position.symbol != symbol:
                    continue
                for trim in partial_target_fills(
                    position, bar, spread_pct=config.default_spread_pct,
                    slippage_points=config.slippage_points,
                ):
                    portfolio.exit(trim)
                    exits.append(trim)
                    level = 3 if trim.reason == "TRIM_3R" else 5
                    portfolio.replace(portfolio.positions[position.position_id].mark_trim(level))
                    event(tick.at, EventKind.TRIM, trim.reason,
                          {"points": str(trim.exit_points), "volume": str(trim.volume),
                           "pnl_gbp": str(trim.pnl_gbp)})
            known = bars_known_at(daily, tick.at)
            if tick.at >= session.close_local - timedelta(minutes=5):
                for position in tuple(portfolio.positions.values()):
                    trail_key = (position.position_id, session.trading_date.isoformat())
                    if trail_key in evaluated_trails:
                        continue
                    trail = evaluate_forming_ema_trail(
                        position, known, intraday, as_of=tick.at, session=session,
                    )
                    evaluated_trails.add(trail_key)
                    event(tick.at, EventKind.RISK, trail.reason,
                          {"note": trail.note,
                           "forming_ema_points": str(trail.ema_points or "")})
                    if trail.exit_now:
                        quote = assumed_quote(bar.close, spread_pct=config.default_spread_pct,
                                              as_of=tick.at)
                        price = quote.bid_points if position.side == "LONG" else quote.ask_points
                        fill = ExitFill(position.position_id, symbol, tick.at, price,
                                        position.open_volume,
                                        pnl_gbp(position.entry_points, price,
                                                position.stake_gbp, position.side),
                                        trail.reason, quote.assumed)
                        portfolio.exit(fill)
                        exits.append(fill)
                        event(tick.at, EventKind.EXIT, fill.reason,
                              {"points": str(fill.exit_points),
                               "pnl_gbp": str(fill.pnl_gbp)})
                    elif trail.armed != position.ema_trail_armed:
                        portfolio.replace(apply_trail_arm(position, trail))
            context = build_daily_context(known)
            decision = evaluate_pullback(context, as_of=tick.at, price_usd=bar.close)
            if context is None:
                decision = replace(decision, symbol=symbol)
            session_key = (symbol, bar.timestamp.date().isoformat())
            if session_key in submitted_dates or portfolio.positions or book.pending:
                reason = (ReasonCode.DUPLICATE_SIGNAL if session_key in submitted_dates else
                          ReasonCode.MAX_POSITIONS)
                decision = replace(decision, accepted=False, reason=reason.value,
                                   description="Existing order or open position prevents duplicate entry")
            if decision.accepted:
                assert context is not None and context.zone is not None
                stop = context.zone.low - Decimal("0.01")
                risk = assess_risk(
                    entry_usd=bar.close, stop_usd=stop, settings=limit,
                    as_of=tick.at, strategy_version=config.strategy_version,
                    spread_pct=config.default_spread_pct,
                    open_risk_gbp=portfolio.open_risk_gbp,
                    realized_loss_today_gbp=portfolio.daily_realized_losses(
                        bar.timestamp.date()), open_positions=len(portfolio.positions),
                    adr_usd=context.adr,
                )
                if not risk.allowed:
                    decision = replace(decision, accepted=False, reason=risk.reason.value,
                                       description=risk.detail or risk.reason.value)
                else:
                    order = OrderIntent(
                        f"{symbol}:{tick.at.isoformat()}", symbol, OrderSide.LONG,
                        OrderType.MARKET, tick.at, risk.volume,
                        protective_stop_points=risk.stop_points,
                    )
                    book.submit(order)
                    submitted_dates.add(session_key)
                    event(tick.at, EventKind.ORDER_SUBMITTED, "RISK_APPROVED",
                          {"budget_gbp": str(risk.budget_gbp),
                           "reserved_gbp": str(risk.risk_gbp)})
            decisions.append(decision)
            events.append(decision.as_event(len(events)))
            if last_price:
                mark = portfolio.mark(last_price, as_of=tick.at)
                snapshots.append(mark)
    portfolio.verify()
    final = snapshots[-1].equity_gbp if snapshots else config.initial_equity_gbp
    return ReplayResult(symbol, config.strategy_version, source_digest,
                        tuple(events), tuple(decisions), tuple(entries), tuple(exits),
                        tuple(snapshots), config.initial_equity_gbp, final,
                        len(portfolio.positions), portfolio.cash_gbp,
                        source_kind="synthetic" if source_digest == "synthetic" else "user_supplied",
                        timeframe="minute",
                        first_date=intraday[0].timestamp.date().isoformat(),
                        last_date=intraday[-1].timestamp.date().isoformat())
