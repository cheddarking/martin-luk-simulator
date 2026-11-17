"""Contract for real daily Yahoo-shaped CSVs; test rows are invented."""

from pathlib import Path
from decimal import Decimal

import pytest

from luk_replay.ingest.daily_csv import DailyImportError, read_yahoo_daily

FIXTURE = Path(__file__).parent / "fixtures" / "daily_yahoo_format.csv"


def test_date_only_csv_maps_to_true_early_close_and_keeps_symbol_provenance(tmp_path: Path) -> None:
    path = tmp_path / "EXAMPLE.csv"
    path.write_bytes(FIXTURE.read_bytes())
    result = read_yahoo_daily(path, adjustment="unknown")
    assert result.symbol == "EXAMPLE"
    assert result.source_kind == "yfinance_cache"
    assert len(result.sha256) == 64
    assert len(result.bars) == 2
    assert result.bars[0].timestamp.hour == 9
    assert result.bars[0].end_time.hour == 16
    assert result.bars[1].end_time.hour == 13
    assert result.bars[1].close == Decimal("102.13")
    assert result.rounded_cells >= 1
    assert result.first_date.isoformat() == "2025-11-26"
    assert result.last_date.isoformat() == "2025-11-28"


def test_duplicate_or_nontrading_dates_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "EXAMPLE.csv"
    path.write_text("Date,Close,High,Low,Open,Volume\n"
                    "2026-11-25,100,101,99,100,1000\n"
                    "2026-11-25,100,101,99,100,1000\n", encoding="utf-8")
    with pytest.raises(DailyImportError, match=r"line 3.*duplicate"):
        read_yahoo_daily(path)
    path.write_text("Date,Close,High,Low,Open,Volume\n"
                    "2026-11-26,100,101,99,100,1000\n", encoding="utf-8")
    with pytest.raises(DailyImportError, match=r"line 2.*closed"):
        read_yahoo_daily(path)


def test_symbol_is_derived_from_safe_filename_not_spreadsheet_content(tmp_path: Path) -> None:
    path = tmp_path / "bad name.csv"
    with pytest.raises(DailyImportError, match="symbol"):
        read_yahoo_daily(path)
