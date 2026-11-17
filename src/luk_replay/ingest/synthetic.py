"""Reproducible synthetic candles. These are *not* historical trade records."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from luk_replay.domain.bar import Bar
from luk_replay.market.calendar import USMarketCalendar


SCENARIOS = {"steady", "pullback", "gap_down", "chop", "breakout"}
NY = ZoneInfo("America/New_York")


def make_session(
    date: str = "2026-11-16", *, symbol: str = "EXAMPLE", scenario: str = "pullback",
    minutes: int = 390, initial: Decimal = Decimal("115.00"),
) -> tuple[Bar, ...]:
    """Create a deterministic session with varied, valid OHLCV and no random state."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown synthetic scenario: {scenario}")
    if not 1 <= minutes <= 390:
        raise ValueError("minutes must be within a regular trading session")
    start = datetime.fromisoformat(date).replace(hour=9, minute=30, tzinfo=NY)
    if start.weekday() >= 5:
        raise ValueError("synthetic session requires a weekday")
    price = initial
    bars: list[Bar] = []
    for minute in range(minutes):
        # A deterministic pattern with an obvious pullback and recovery.
        oscillation = Decimal((minute * 7) % 11 - 5) * Decimal("0.01")
        trend = Decimal("0.02") if minute % 7 < 5 else Decimal("-0.03")
        if scenario == "pullback" and 20 <= minute <= 31:
            trend = Decimal("-0.08")
        if scenario == "pullback" and 32 <= minute <= 49:
            trend = Decimal("0.10")
        if scenario == "gap_down" and minute == 0:
            price -= Decimal("4")
        if scenario == "chop":
            trend = Decimal("0.03") if minute % 2 else Decimal("-0.03")
        if scenario == "breakout" and 30 <= minute <= 43:
            trend = Decimal("0.14")
        opening = price.quantize(Decimal("0.01"))
        closing = (opening + trend + oscillation).quantize(Decimal("0.01"))
        upper = max(opening, closing) + Decimal("0.03")
        lower = min(opening, closing) - Decimal("0.03")
        bars.append(Bar(start + timedelta(minutes=minute), symbol, opening, upper,
                        lower, closing, 700 + (minute * 113) % 800))
        price = closing
    return tuple(bars)


def make_daily_lookback(
    *, through: date = date(2026, 11, 13), symbol: str = "EXAMPLE",
    sessions: int = 60,
) -> tuple[Bar, ...]:
    """Invent rising daily closes for the demo without exposing future prices."""
    if sessions < 50 or sessions > 300:
        raise ValueError("daily demo lookback must cover between 50 and 300 sessions")
    calendar = USMarketCalendar()
    start = through - timedelta(days=sessions * 2 + 20)
    days = calendar.sessions(start, through)[-sessions:]
    if len(days) != sessions:
        raise ValueError("not enough simulated market sessions for requested history")
    output = []
    for index, trading_session in enumerate(days):
        close = Decimal("100.00") + Decimal(index) * Decimal("0.20")
        output.append(Bar(trading_session.open_local, symbol, close,
                          close + Decimal("0.20"), close - Decimal("0.20"),
                          close, 1000 + index * 5, 86400))
    return tuple(output)


def write_session(path: Path, bars: tuple[Bar, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("timestamp", "symbol", "open", "high", "low", "close", "volume"))
        for b in bars:
            writer.writerow((b.timestamp.isoformat(), b.symbol, b.open, b.high,
                             b.low, b.close, b.volume))
    return path
