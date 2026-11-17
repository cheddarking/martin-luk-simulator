"""Only an actual local daily price file can enter a history catalog."""

from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json

import pytest

from luk_replay.ingest.daily_csv import DailyImportError
from luk_replay.ingest.history_catalog import discover_history, select_history

FIXTURE = Path(__file__).parent / "fixtures" / "daily_yahoo_format.csv"


def test_targeted_catalog_does_not_scan_all_other_tickers(tmp_path: Path) -> None:
    (tmp_path / "AAPL.csv").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "ZZZ.csv").write_text("not,an,ohlcv,file\n", encoding="utf-8")
    records = discover_history(tmp_path, symbols=["AAPL"])
    assert list(records) == ["AAPL"]


def test_modified_price_file_cannot_keep_old_source_digest(tmp_path: Path) -> None:
    (tmp_path / "AAPL.csv").write_bytes(FIXTURE.read_bytes())
    (tmp_path / "AAPL.meta.json").write_text(json.dumps({
        "source": "yfinance_six_year", "adjustment": "yahoo_auto_adjust_false",
        "sha256": "f" * 64}), encoding="utf-8")
    with pytest.raises(DailyImportError, match="digest"):
        select_history(tmp_path, "AAPL")


def test_current_forming_daily_bar_is_not_replayed_as_completed(tmp_path: Path) -> None:
    csv_text = ("Date,Close,High,Low,Open,Volume\n"
                "2026-11-16,100,101,99,100,1000\n"
                "2026-11-17,101,102,100,101,1000\n")
    (tmp_path / "AAPL.csv").write_text(csv_text, encoding="utf-8")
    midday = datetime(2026, 11, 17, 11, 45, tzinfo=ZoneInfo("America/New_York"))
    history = select_history(tmp_path, "AAPL", as_of=midday)
    assert len(history.bars) == 1
    assert history.last_date.isoformat() == "2026-11-16"


def test_two_distant_rows_are_not_six_year_coverage(tmp_path: Path) -> None:
    (tmp_path / "AAPL.csv").write_text(
        "Date,Close,High,Low,Open,Volume\n"
        "2020-11-17,100,101,99,100,1000\n"
        "2026-11-16,101,102,100,101,1000\n", encoding="utf-8")
    record = discover_history(tmp_path)["AAPL"]
    assert record.sessions == 2
    assert record.complete_six_years is False


def test_catalog_reports_real_coverage_without_copying_price_data(tmp_path: Path) -> None:
    folder = tmp_path / "private-bars"
    folder.mkdir()
    (folder / "AAPL.csv").write_bytes(FIXTURE.read_bytes())
    (folder / "universe.csv").write_text("symbol\nAAPL\n", encoding="utf-8")
    records = discover_history(folder)
    assert list(records) == ["AAPL"]
    assert records["AAPL"].first_date.isoformat() == "2025-11-26"
    assert records["AAPL"].last_date.isoformat() == "2025-11-28"
    assert records["AAPL"].complete_six_years is False
    assert records["AAPL"].path == folder / "AAPL.csv"
