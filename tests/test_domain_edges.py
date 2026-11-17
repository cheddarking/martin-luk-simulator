"""Boundary behavior for units, indicators, structure and as-of snapshots."""

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from luk_replay.domain.bar import Bar
from luk_replay.domain.units import (UnitError, from_broker_points, pnl_gbp,
                                     risk_gbp, volume_for_stake)
from luk_replay.market.anchors import anchored_vwap_series, highest_volume_anchor
from luk_replay.market.asof import last_completed, snapshot
from luk_replay.market.indicators import (average_daily_range, average_volume,
                                          exponential_average, simple_moving_average)
from luk_replay.market.structure import (higher_lows, recent_resistance,
                                         recent_support)

NY = ZoneInfo("America/New_York")


def sample_bars() -> tuple[Bar, ...]:
    start = datetime(2026, 11, 16, 9, 30, tzinfo=NY)
    return (
        Bar(start, "EXAMPLE", Decimal("100"), Decimal("101"),
            Decimal("99"), Decimal("100"), 0),
        Bar(start + timedelta(minutes=1), "EXAMPLE", Decimal("101"), Decimal("102"),
            Decimal("100"), Decimal("101"), 200),
        Bar(start + timedelta(minutes=2), "EXAMPLE", Decimal("102"), Decimal("103"),
            Decimal("101"), Decimal("102"), 400),
    )


def test_units_do_not_confuse_dollars_points_and_gbp_stake() -> None:
    assert from_broker_points(Decimal("11504")) == Decimal("115.04")
    assert volume_for_stake(Decimal("0.10")) == 10
    assert risk_gbp(Decimal("11504"), Decimal("11400"), Decimal("0.10")) == Decimal("10.40")
    assert pnl_gbp(Decimal("10000"), Decimal("9900"), Decimal("0.10"), "SHORT") == Decimal("10.00")
    with pytest.raises(UnitError, match="penny granularity"):
        volume_for_stake(Decimal("0.115"))
    with pytest.raises(UnitError, match="integral"):
        from_broker_points(Decimal("1.5"))
    with pytest.raises(UnitError, match="finite"):
        volume_for_stake(Decimal("NaN"))


def test_asof_snapshot_never_includes_a_partial_bar() -> None:
    bars = sample_bars()
    now = bars[1].end_time
    assert last_completed(bars, now) == bars[1]
    view = snapshot("EXAMPLE", now, one_minute=bars)
    assert view.one_minute == bars[:2]
    assert view.latest_close() == Decimal("101")
    with pytest.raises(ValueError, match="timezone"):
        last_completed(bars, datetime(2026, 11, 16, 9, 31))


def test_anchored_vwap_respects_zero_volume_and_anchor_time() -> None:
    bars = sample_bars()
    values = anchored_vwap_series(bars)
    assert values[0] is None
    assert values[1] == Decimal("101.0000")
    assert values[2] == Decimal("101.6667")
    assert highest_volume_anchor(bars) == bars[2].timestamp
    assert anchored_vwap_series(bars, from_time=bars[2].timestamp)[:2] == (None, None)


def test_smoothing_and_structure_require_enough_observations() -> None:
    bars = sample_bars()
    assert simple_moving_average(bars, 4) is None
    assert simple_moving_average(bars, 2) == Decimal("101.5")
    assert average_volume(bars, 3) == Decimal("200")
    assert average_daily_range(bars, 3) == Decimal("2")
    assert exponential_average((Decimal(1), Decimal(3)), 3) == (
        Decimal(1), Decimal(2))
    assert recent_resistance(bars, lookback=2) == Decimal("103")
    support = recent_support(bars)
    assert support is not None and support.low == Decimal("99")
    assert support.contains(Decimal("99.1"))
    assert support.distance_pct(Decimal("102")) > 0
    assert higher_lows(bars)
    with pytest.raises(ValueError, match="positive"):
        average_volume(bars, 0)
