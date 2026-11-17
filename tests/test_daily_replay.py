"""Daily swing decisions happen after closes and execute no earlier than next open."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from luk_replay.domain.bar import Bar
from luk_replay.engine.daily_replay import replay_daily
from luk_replay.ingest.daily_csv import DailyHistory
from luk_replay.market.calendar import USMarketCalendar


def daily_case(*, next_low: Decimal = Decimal("111.00"),
               last_date: date = date(2026, 11, 16)) -> DailyHistory:
    calendar = USMarketCalendar()
    sessions = calendar.sessions(date(2026, 7, 1), last_date)[-61:]
    bars: list[Bar] = []
    for index, day in enumerate(sessions[:60]):
        close = Decimal("100") + Decimal(index) * Decimal("0.20")
        if index == 59:
            close = Decimal("111.20")
        bars.append(Bar(day.open_local, "EXAMPLE", close, close + Decimal("0.90"),
                        close - Decimal("0.10"), close, 1000,
                        timeframe_seconds=day.trading_minutes * 60))
    following = sessions[60]
    bars.append(Bar(following.open_local, "EXAMPLE", Decimal("111.30"),
                    Decimal("112.00"), next_low, Decimal("111.40"), 1000,
                    timeframe_seconds=following.trading_minutes * 60))
    return DailyHistory(Path("synthetic-test-only.csv"), "EXAMPLE", tuple(bars),
                        "0" * 64, "synthetic_test", "unknown", 0,
                        bars[0].timestamp.date(), bars[-1].timestamp.date())


def test_signal_at_close_cannot_fill_before_next_session_open() -> None:
    history = daily_case()
    result = replay_daily(history)
    assert result.accepted_count >= 1
    assert result.entries
    first_entry = result.entries[0]
    signal = next(event for event in result.events if event.reason == "RISK_APPROVED")
    assert signal.as_of == history.bars[-2].end_time
    assert first_entry.filled_at == history.bars[-1].timestamp
    assert first_entry.filled_at > signal.as_of
    assert all(event.sequence == n for n, event in enumerate(result.events))


def test_daily_stop_known_at_close_not_previous_open() -> None:
    history = daily_case(next_low=Decimal("110.50"))
    result = replay_daily(history)
    assert len(result.entries) == 1
    assert len(result.exits) == 1
    assert result.exits[0].reason == "STOP_FILLED"
    assert result.exits[0].filled_at == history.bars[-1].end_time
    assert result.ending_cash_gbp < result.initial_equity_gbp


def test_daily_replay_preserves_rule_dates_on_early_close() -> None:
    history = daily_case(last_date=date(2026, 11, 27))
    result = replay_daily(history, start_date=history.bars[-2].timestamp.date())
    assert result.decisions[0].as_of == history.bars[-2].end_time
    assert result.decisions[0].as_of.hour == 16
    assert result.entries[0].filled_at == history.bars[-1].timestamp
    assert history.bars[-1].end_time.hour == 13
    assert history.bars[-2].timestamp.date() == date(2026, 11, 25)
