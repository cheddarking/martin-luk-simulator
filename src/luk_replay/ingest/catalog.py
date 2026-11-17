"""Provenance records for reproducible local market data imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from luk_replay.domain.bar import Bar

from .csv_import import read_bars
from .quality import QualityReport, inspect_bars


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    source_name: str
    sha256: str
    bar_count: int
    symbols: tuple[str, ...]
    timeframe_seconds: int
    redistribution: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.redistribution not in {"synthetic", "user_supplied"}:
            raise ValueError("redistribution must be synthetic or user_supplied")
        if self.bar_count <= 0 or len(self.sha256) != 64:
            raise ValueError("invalid source digest or empty import")

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def catalog_path(path: Path, *, redistribution: str = "user_supplied",
                 timeframe_seconds: int = 60) -> tuple[CatalogEntry, QualityReport]:
    bars = read_bars(path, timeframe_seconds=timeframe_seconds)
    report = inspect_bars(bars, expected_seconds=timeframe_seconds)
    entry = CatalogEntry(
        source_name=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bar_count=len(bars), symbols=report.symbols,
        timeframe_seconds=timeframe_seconds, redistribution=redistribution,
        notes="Use a locally held source; no license is inferred from a price CSV.",
    )
    return entry, report
