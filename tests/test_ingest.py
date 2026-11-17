"""Observable CSV import and GBP spread-bet unit contracts."""

from decimal import Decimal
from pathlib import Path

import pytest

from luk_replay.domain.units import stake_for_volume, to_broker_points
from luk_replay.ingest.csv_import import CSVImportError, read_bars


HEADER = "timestamp,symbol,open,high,low,close,volume\n"


def write_csv(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def test_rejects_duplicate_timestamp_and_preserves_broker_point_units(tmp_path: Path) -> None:
    rows = (
        "2026-11-16T09:30:00-05:00,EXAMPLE,115.00,115.10,114.95,115.04,1000\n"
        "2026-11-16T09:30:00-05:00,EXAMPLE,115.01,115.10,114.95,115.04,1000\n"
    )
    with pytest.raises(CSVImportError, match=r"line 3.*duplicate"):
        read_bars(write_csv(tmp_path, rows))
    assert to_broker_points(Decimal("115.04")) == Decimal("11504")
    assert stake_for_volume(10) == Decimal("0.10")


def test_valid_import_is_ordered_and_immutable(tmp_path: Path) -> None:
    path = write_csv(
        tmp_path,
        "2026-11-16T09:30:00-05:00,EXAMPLE,115,116,114,115.5,1000\n"
        "2026-11-16T09:31:00-05:00,EXAMPLE,115.5,116,115,115.7,1200\n",
    )
    bars = read_bars(path)
    assert len(bars) == 2
    assert bars[0].close == Decimal("115.5")
    assert bars[1].timestamp > bars[0].timestamp
    with pytest.raises(AttributeError):
        bars[0].close = Decimal("0")


def test_naive_and_out_of_order_timestamps_are_rejected(tmp_path: Path) -> None:
    naive = "2026-11-16T09:30:00,EXAMPLE,115,116,114,115.5,1000\n"
    with pytest.raises(CSVImportError, match="timezone"):
        read_bars(write_csv(tmp_path, naive))
    backwards = (
        "2026-11-16T09:31:00-05:00,EXAMPLE,115,116,114,115.5,1000\n"
        "2026-11-16T09:30:00-05:00,EXAMPLE,115,116,114,115.5,1000\n"
    )
    with pytest.raises(CSVImportError, match=r"line 3.*out of order"):
        read_bars(write_csv(tmp_path, backwards))
