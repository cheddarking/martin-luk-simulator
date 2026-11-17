"""Temporal integrity of the market clock and price features."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from luk_replay.domain.bar import Bar
from luk_replay.market.aggregation import aggregate_bars
from luk_replay.market.asof import bars_known_at
from luk_replay.market.calendar import USMarketCalendar
from luk_replay.market.indicators import ema_series
from luk_replay.market.anchors import anchored_vwap


NY = ZoneInfo("America/New_York")


def bars() -> tuple[Bar, ...]:
    origin = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    return tuple(Bar(origin + timedelta(minutes=i), "EXAMPLE",
                     Decimal(100+i), Decimal(101+i), Decimal(99+i),
                     Decimal(100+i), 100) for i in range(6))


def test_asof_view_excludes_current_incomplete_bar_and_next_day() -> None:
    data = bars()
    first_end = data[0].end_time
    assert bars_known_at(data, first_end - timedelta(seconds=1)) == ()
    assert bars_known_at(data, first_end) == data[:1]
    assert bars_known_at(data, data[2].timestamp + timedelta(seconds=1)) == data[:2]
    assert bars_known_at(data, data[-1].end_time) == data


def test_aggregation_does_not_expose_incomplete_five_minute_bar() -> None:
    data = bars()
    asof = data[4].timestamp + timedelta(seconds=30)
    assert aggregate_bars(data, 300, asof=asof) == ()
    completed = aggregate_bars(data, 300, asof=data[4].end_time)
    assert len(completed) == 1
    assert completed[0].open == Decimal(100)
    assert completed[0].close == Decimal(104)
    assert completed[0].volume == 500


def test_market_clock_changes_utc_offset_and_handles_early_close() -> None:
    calendar = USMarketCalendar()
    winter = calendar.session(date(2026, 11, 16))
    summer = calendar.session(date(2026, 7, 16))
    assert winter.open_utc.hour == 14
    assert summer.open_utc.hour == 13
    early = calendar.session(date(2026, 11, 27))
    assert early.close_local.hour == 13
    with pytest.raises(ValueError, match="closed"):
        calendar.session(date(2026, 12, 25))


def test_juneteenth_nyse_closure_starts_in_2022() -> None:
    calendar = USMarketCalendar()
    assert calendar.is_open(date(2021, 6, 18))
    assert not calendar.is_open(date(2022, 6, 20))


def test_nyse_does_not_observe_saturday_new_year_on_previous_friday() -> None:
    calendar = USMarketCalendar()
    assert calendar.is_open(date(2021, 12, 31))
    assert not calendar.is_open(date(2023, 1, 2))


def test_ema_and_anchored_vwap_use_only_provided_bars() -> None:
    data = bars()
    first = ema_series(data[:3], 3)
    extended = ema_series(data, 3)
    assert first == extended[:3]
    assert anchored_vwap(data[:2]) == Decimal("100.5000")
