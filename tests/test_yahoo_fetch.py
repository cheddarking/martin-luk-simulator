"""Acquisition tests never contact Yahoo or bundle actual historical prices."""

from datetime import date, datetime, timedelta, timezone
import sys
from types import SimpleNamespace
from decimal import Decimal
from pathlib import Path

import pytest

from luk_replay.ingest.yahoo_fetch import FetchError, _provider_rows, fetch_history
from luk_replay.ingest.history_catalog import discover_history
from luk_replay.market.calendar import USMarketCalendar


def sample_rows(start: date, sessions: int) -> list[dict[str, object]]:
    output = []
    current = start
    while len(output) < sessions:
        if USMarketCalendar().is_open(current):
            output.append({"Date": current.isoformat(), "Open": "100.00", "High": "101.00",
                           "Low": "99.00", "Close": "100.25", "Volume": 1000,
                           "Stock Splits": 0, "Dividends": 0})
        current += timedelta(days=1)
    return output


def test_missing_or_partial_history_fails_completeness_without_network(tmp_path: Path) -> None:
    calls = []
    def provider(symbol: str, start: date, end: date):
        calls.append((symbol, start, end))
        return sample_rows(date(2024, 11, 14), 501)
    report = fetch_history(["AAPL"], start=date(2020, 11, 17),
                           end=date(2026, 11, 17), cache_dir=tmp_path,
                           fetcher=provider, pause_seconds=0)
    assert calls == [("AAPL", date(2020, 11, 17), date(2026, 11, 17))]
    assert report.results["AAPL"].complete_six_years is False
    assert report.results["AAPL"].first_date == date(2024, 11, 14)
    assert (tmp_path / "AAPL.csv").is_file()
    assert discover_history(tmp_path)["AAPL"].source_kind == "yfinance_six_year"


def test_long_but_partial_history_reports_provenance_and_date_bounds(tmp_path: Path) -> None:
    def provider(symbol: str, start: date, end: date):
        return sample_rows(date(2020, 11, 17), 900)
    report = fetch_history(["MSFT"], start=date(2020, 11, 17),
                           end=date(2026, 11, 17), cache_dir=tmp_path,
                           fetcher=provider, pause_seconds=0)
    entry = report.results["MSFT"]
    # A source can have enough rows but still stop months too early.
    assert entry.complete_six_years is False
    assert entry.sessions == 900
    assert entry.adjustment == "yahoo_auto_adjust_false"
    assert len(entry.sha256) == 64


def test_full_six_year_history_is_marked_complete(tmp_path: Path) -> None:
    first, end = date(2020, 11, 17), date(2026, 11, 17)
    def provider(symbol: str, start: date, until: date):
        days = USMarketCalendar().sessions(first, end - timedelta(days=1))
        return [{"Date": day.trading_date.isoformat(), "Open": "100.00",
                 "High": "101.00", "Low": "99.00", "Close": "100.25",
                 "Volume": 1000, "Stock Splits": 0, "Dividends": 0}
                for day in days]
    report = fetch_history(["AAPL"], start=first, end=end,
                           cache_dir=tmp_path, fetcher=provider, pause_seconds=0)
    assert report.results["AAPL"].complete_six_years is True


def test_yfinance_dataframe_float_volume_is_exact_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    class Frame:
        empty = False
        columns = {"Open", "High", "Low", "Close", "Volume"}
        def iterrows(self):
            yield datetime(2026, 11, 16, tzinfo=timezone.utc), {
                "Open": 100.0, "High": 101.0, "Low": 99.0,
                "Close": 100.25, "Volume": 1234.0}
    class Ticker:
        def __init__(self, symbol: str):
            self.symbol = symbol
        def history(self, **kwargs):
            return Frame()
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=Ticker))
    rows = _provider_rows("AAPL", date(2026, 11, 16), date(2026, 11, 17))
    assert rows[0]["Volume"] == 1234
    assert type(rows[0]["Volume"]) is int


def test_provider_error_is_reported_without_overwriting_existing_data(tmp_path: Path) -> None:
    def unavailable(symbol: str, start: date, end: date):
        raise RuntimeError("temporarily unavailable")
    report = fetch_history(["AAPL"], start=date(2020, 11, 17),
                           end=date(2026, 11, 17), cache_dir=tmp_path,
                           fetcher=unavailable, pause_seconds=0)
    assert report.complete is False
    assert "temporarily unavailable" in report.errors["AAPL"]
    assert not (tmp_path / "AAPL.csv").exists()


def test_fetch_rejects_unsafe_symbol_and_public_repo_destination(tmp_path: Path) -> None:
    with pytest.raises(FetchError, match="symbol"):
        fetch_history(["../../unsafe"], start=date(2020, 11, 17),
                      end=date(2026, 11, 17), cache_dir=tmp_path,
                      fetcher=lambda *_: [], pause_seconds=0)
    repo_root = Path(__file__).resolve().parents[1]
    with pytest.raises(FetchError, match="private"):
        fetch_history(["AAPL"], start=date(2020, 11, 17),
                      end=date(2026, 11, 17), cache_dir=repo_root / "public-data",
                      fetcher=lambda *_: [], pause_seconds=0)
