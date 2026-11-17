"""Gap fills, position accounting and ledger invariants."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from luk_replay.domain.bar import Bar
from luk_replay.domain.position import Position
from luk_replay.domain.settings import ReplaySettings, RiskSettings
from luk_replay.engine.fills import exit_on_bar
from luk_replay.engine.ledger import Ledger
from luk_replay.ingest.synthetic import make_daily_lookback
from luk_replay.engine.replay import replay
from luk_replay.market.calendar import USMarketCalendar
from luk_replay.strategy.exits import evaluate_forming_ema_trail, partial_target_fills


NY = ZoneInfo("America/New_York")


def test_gap_through_stop_uses_gap_fill_and_balances_ledger() -> None:
    start = datetime(2026, 11, 16, 15, 50, tzinfo=NY)
    position = Position(
        position_id="p1", symbol="EXAMPLE", side="LONG", opened_at=start,
        entry_points=Decimal("10000"), stop_points=Decimal("9800"), volume=10,
    )
    next_open = Bar(
        start + timedelta(days=1, hours=-6, minutes=-20), "EXAMPLE",
        Decimal("95.00"), Decimal("96.00"), Decimal("94.00"),
        Decimal("95.00"), 1000,
    )
    result = exit_on_bar(position, next_open, spread_pct=Decimal("0"))
    assert result is not None
    assert result.reason == "GAP_THROUGH_STOP"
    assert result.exit_points == Decimal("9500")
    assert result.pnl_gbp == Decimal("-50.00")
    ledger = Ledger()
    ledger.record_exit(result)
    assert ledger.balance() == Decimal("0.00")
    assert ledger.realized_pnl() == Decimal("-50.00")


def test_same_bar_target_and_stop_conservatively_prefers_stop() -> None:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    position = Position("p2", "EXAMPLE", "LONG", start, Decimal("10000"),
                        Decimal("9900"), 10, target_points=Decimal("10300"))
    bar = Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("100.00"),
              Decimal("104.00"), Decimal("98.00"), Decimal("101.00"), 1000)
    result = exit_on_bar(position, bar, spread_pct=Decimal("0"))
    assert result is not None
    assert result.reason == "STOP_FILLED"
    assert result.exit_points == Decimal("9900")


def test_replay_decides_at_close_and_fills_only_on_next_open() -> None:
    dates = USMarketCalendar().sessions(
        datetime(2026, 7, 1).date(), datetime(2026, 11, 13).date()
    )[-60:]
    history = []
    for i, session in enumerate(dates):
        close = Decimal("100.00") + Decimal(i) * Decimal("0.20")
        history.append(Bar(session.open_local, "EXAMPLE", close, close + Decimal("0.20"),
                           close - Decimal("0.20"), close, 1000, 86400))
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    intraday = (
        Bar(start, "EXAMPLE", Decimal("107.98"), Decimal("108.10"),
            Decimal("107.90"), Decimal("107.98"), 1000),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("108.05"),
            Decimal("108.20"), Decimal("108.00"), Decimal("108.10"), 1000),
    )
    result = replay(intraday, daily=history)
    assert result.accepted_count == 1
    assert len(result.entries) == 1
    assert result.entries[0].filled_at == intraday[1].timestamp
    assert result.events[0].kind == "BAR_COMPLETED"
    assert all(event.sequence == n for n, event in enumerate(result.events))


def test_entry_bar_stop_is_not_deferred_to_next_bar() -> None:
    dates = USMarketCalendar().sessions(
        datetime(2026, 7, 1).date(), datetime(2026, 11, 13).date()
    )[-60:]
    history = []
    for i, session in enumerate(dates):
        close = Decimal("100.00") + Decimal(i) * Decimal("0.20")
        history.append(Bar(session.open_local, "EXAMPLE", close, close + Decimal("0.20"),
                           close - Decimal("0.20"), close, 1000, 86400))
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    intraday = (
        Bar(start, "EXAMPLE", Decimal("107.98"), Decimal("108.10"),
            Decimal("107.90"), Decimal("107.98"), 1000),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("108.05"),
            Decimal("108.20"), Decimal("107.50"), Decimal("108.00"), 1000),
    )
    result = replay(intraday, daily=history)
    assert len(result.entries) == 1
    assert len(result.exits) == 1
    assert result.exits[0].reason == "STOP_FILLED"
    assert result.exits[0].filled_at == intraday[1].end_time  # OHLC does not reveal intrabar clock time.


def test_partial_trim_executes_only_at_representable_stake_and_once_per_level() -> None:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    position = Position("p4", "EXAMPLE", "LONG", start, Decimal("10000"),
                        Decimal("9900"), 100)
    bar = Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("100.00"),
              Decimal("105.10"), Decimal("99.95"), Decimal("104.00"), 1000)
    fills = partial_target_fills(position, bar, spread_pct=Decimal("0"))
    assert [fill.reason for fill in fills] == ["TRIM_3R", "TRIM_5R"]
    assert [fill.volume for fill in fills] == [10, 10]
    assert [fill.exit_points for fill in fills] == [Decimal("10300"), Decimal("10500")]
    assert all(fill.filled_at == bar.end_time for fill in fills)
    assert partial_target_fills(position.mark_trim(3).mark_trim(5), bar,
                                spread_pct=Decimal("0")) == ()


def test_forming_daily_trail_uses_only_completed_intraday_bars() -> None:
    calendar = USMarketCalendar()
    dates = calendar.sessions(datetime(2026, 7, 1).date(),
                              datetime(2026, 11, 13).date())[-25:]
    daily = tuple(Bar(session.open_local, "EXAMPLE", Decimal("100"),
                      Decimal("101"), Decimal("99"), Decimal("100"), 1000, 86400)
                  for session in dates)
    now = datetime(2026, 11, 16, 15, 55, tzinfo=NY)
    current = (Bar(now - timedelta(minutes=1), "EXAMPLE", Decimal("90"),
                   Decimal("91"), Decimal("89"), Decimal("90"), 1000),)
    position = Position("p5", "EXAMPLE", "LONG", dates[-2].open_local,
                        Decimal("10000"), Decimal("9500"), 10,
                        ema_trail_armed=True)
    verdict = evaluate_forming_ema_trail(position, daily, current,
                                         as_of=now, session=calendar.session(now.date()))
    assert verdict.exit_now is True
    assert verdict.reason == "EOD_EMA_EXIT"
    same_day = Position("p6", "EXAMPLE", "LONG", now - timedelta(minutes=30),
                        Decimal("10000"), Decimal("9500"), 10,
                        ema_trail_armed=True)
    assert evaluate_forming_ema_trail(same_day, daily, current, as_of=now,
                                      session=calendar.session(now.date())).exit_now is False


def test_forming_close_alone_does_not_arm_trail() -> None:
    calendar = USMarketCalendar()
    dates = calendar.sessions(datetime(2026, 7, 1).date(),
                              datetime(2026, 11, 13).date())[-25:]
    daily = tuple(Bar(session.open_local, "EXAMPLE", Decimal("100"),
                      Decimal("101"), Decimal("99"), Decimal("100"), 1000, 86400)
                  for session in dates)
    now = datetime(2026, 11, 16, 15, 55, tzinfo=NY)
    current = (Bar(now - timedelta(minutes=1), "EXAMPLE", Decimal("110"),
                   Decimal("111"), Decimal("109"), Decimal("110"), 1000),)
    position = Position("p7", "EXAMPLE", "LONG", dates[-1].open_local,
                        Decimal("10000"), Decimal("9500"), 10)
    verdict = evaluate_forming_ema_trail(position, daily, current,
                                         as_of=now, session=calendar.session(now.date()))
    assert verdict.armed is False
    assert verdict.exit_now is False


def test_replay_records_representable_partial_trim_in_ledger() -> None:
    daily = []
    dates = USMarketCalendar().sessions(
        datetime(2026, 7, 1).date(), datetime(2026, 11, 13).date()
    )[-60:]
    for i, session in enumerate(dates):
        close = Decimal("100.00") + Decimal(i) * Decimal("0.20")
        daily.append(Bar(session.open_local, "EXAMPLE", close, close + Decimal("0.20"),
                         close - Decimal("0.20"), close, 1000, 86400))
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    intraday = (
        Bar(start, "EXAMPLE", Decimal("107.98"), Decimal("108.10"),
            Decimal("107.90"), Decimal("107.98"), 1000),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("108.05"),
            Decimal("110.00"), Decimal("108.00"), Decimal("109.00"), 1000),
    )
    result = replay(intraday, daily=daily,
                    settings=ReplaySettings(initial_equity_gbp=Decimal("100000")),
                    risk_settings=RiskSettings(equity_gbp=Decimal("100000")))
    assert len(result.entries) == 1
    assert any(exit.reason == "TRIM_3R" for exit in result.exits)
    assert any(event.kind == "TRIM" for event in result.events)
    assert result.ending_cash_gbp > result.initial_equity_gbp


def test_next_open_beyond_stop_rejects_instead_of_crashing() -> None:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    bars = (
        Bar(start, "EXAMPLE", Decimal("107.98"), Decimal("108.10"),
            Decimal("107.90"), Decimal("107.98"), 1000),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("107.50"),
            Decimal("107.60"), Decimal("107.40"), Decimal("107.50"), 1000),
    )
    result = replay(bars, daily=make_daily_lookback())
    assert result.entries == ()
    assert any(event.reason == "STOP_INVALID_SIDE" for event in result.events)


def test_next_open_risk_rechecked_against_trade_budget() -> None:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    bars = (
        Bar(start, "EXAMPLE", Decimal("107.98"), Decimal("108.10"),
            Decimal("107.90"), Decimal("107.98"), 1000),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("112.00"),
            Decimal("112.10"), Decimal("111.90"), Decimal("112.00"), 1000),
    )
    result = replay(bars, daily=make_daily_lookback())
    assert result.entries == ()
    assert any(event.reason == "GAP_RISK_EXCEEDED" for event in result.events)
    assert result.ending_cash_gbp == result.initial_equity_gbp


def test_fractional_partial_close_is_rejected_below_minimum_step() -> None:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    position = Position("p3", "EXAMPLE", "LONG", start, Decimal("10000"),
                        Decimal("9800"), 10)
    assert position.can_trim(Decimal("0.15")) is False
