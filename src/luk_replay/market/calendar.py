"""NYSE-style session clock for educational replay, no exchange feed.

Holiday algorithms are local approximations. Overrides support authoritative data
for real imports; never trade a live account using this offline calendar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from luk_replay.domain.session import MarketSession

NY = ZoneInfo("America/New_York")


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    end = first_next - timedelta(days=1)
    return end - timedelta(days=(end.weekday() - weekday) % 7)


def observed(holiday: date) -> date:
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def easter(year: int) -> date:
    """Gregorian Easter; Good Friday is an exchange closure."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f, g = (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def closures(year: int) -> frozenset[date]:
    days = {nth_weekday(year, 1, 0, 3), nth_weekday(year, 2, 0, 3),
            easter(year) - timedelta(days=2), last_weekday(year, 5, 0),
            observed(date(year, 7, 4)),
            nth_weekday(year, 9, 0, 1), nth_weekday(year, 11, 3, 4),
            observed(date(year, 12, 25))}
    # For New Year's Day on Saturday NYSE remains open on Friday Dec 31.
    # For Sunday Jan 1 the exchange instead closes on Monday Jan 2.
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        days.add(new_year + timedelta(days=1))
    elif new_year.weekday() < 5:
        days.add(new_year)
    # NYSE first observed Juneteenth in 2022; it traded on 18 June 2021.
    if year >= 2022:
        days.add(observed(date(year, 6, 19)))
    return frozenset(days)


def typical_early_closes(year: int) -> frozenset[date]:
    thanksgiving = nth_weekday(year, 11, 3, 4)
    candidates = {thanksgiving + timedelta(days=1), date(year, 12, 24)}
    july_third = date(year, 7, 3)
    if july_third.weekday() < 5:
        candidates.add(july_third)
    return frozenset(d for d in candidates if d.weekday() < 5 and d not in closures(year))


@dataclass(frozen=True, slots=True)
class USMarketCalendar:
    closed_overrides: frozenset[date] = frozenset()
    open_overrides: frozenset[date] = frozenset()
    early_close_overrides: frozenset[date] = frozenset()
    suppress_early_close: frozenset[date] = frozenset()

    def is_open(self, trading_date: date) -> bool:
        if trading_date in self.open_overrides:
            return True
        if trading_date in self.closed_overrides or trading_date.weekday() >= 5:
            return False
        return trading_date not in closures(trading_date.year)

    def session(self, trading_date: date) -> MarketSession:
        if not self.is_open(trading_date):
            raise ValueError(f"market closed on {trading_date.isoformat()}")
        early = (trading_date in self.early_close_overrides or
                 trading_date in typical_early_closes(trading_date.year))
        if trading_date in self.suppress_early_close:
            early = False
        start = datetime.combine(trading_date, time(9, 30), tzinfo=NY)
        end = datetime.combine(trading_date, time(13 if early else 16), tzinfo=NY)
        return MarketSession(trading_date, start, end, early)

    def next_session(self, after: date) -> MarketSession:
        candidate = after + timedelta(days=1)
        for _ in range(366):
            if self.is_open(candidate):
                return self.session(candidate)
            candidate += timedelta(days=1)
        raise ValueError("no trading day found within one year")

    def sessions(self, start: date, end: date) -> tuple[MarketSession, ...]:
        if start > end:
            raise ValueError("start date exceeds end date")
        result = []
        cursor = start
        while cursor <= end:
            if self.is_open(cursor):
                result.append(self.session(cursor))
            cursor += timedelta(days=1)
        return tuple(result)
