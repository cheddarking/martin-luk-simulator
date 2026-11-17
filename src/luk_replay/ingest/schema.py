"""Documented input contract for user-supplied bars."""

from __future__ import annotations

from dataclasses import dataclass

COLUMNS = ("timestamp", "symbol", "open", "high", "low", "close", "volume")
MAX_CSV_BYTES = 24_000_000
MAX_ROWS = 300_000
ALLOWED_SUFFIXES = frozenset({".csv"})


@dataclass(frozen=True, slots=True)
class ImportSchema:
    columns: tuple[str, ...] = COLUMNS
    max_bytes: int = MAX_CSV_BYTES
    max_rows: int = MAX_ROWS
    allow_extended_columns: bool = False

    def validate_header(self, names: list[str] | None) -> None:
        if not names:
            raise ValueError("CSV requires a header")
        missing = set(self.columns) - set(names)
        if missing:
            raise ValueError(f"CSV missing columns: {', '.join(sorted(missing))}")
        if len(names) != len(set(names)):
            raise ValueError("CSV has duplicate columns")
        extra = set(names) - set(self.columns)
        if extra and not self.allow_extended_columns:
            raise ValueError(f"CSV has unsupported columns: {', '.join(sorted(extra))}")
