"""Canonical, lossless JSON for Decimal-backed replay snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from luk_replay.engine.replay import ReplayResult


def safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive timestamp cannot be serialized in audit trail")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return safe_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): safe_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [safe_value(item) for item in value]
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(safe_value(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def run_summary(result: ReplayResult) -> dict[str, Any]:
    return {
        "symbol": result.symbol,
        "strategy_version": result.strategy_version,
        "source_digest": result.source_digest,
        "source_kind": result.source_kind,
        "adjustment": result.adjustment,
        "timeframe": result.timeframe,
        "first_date": result.first_date,
        "last_date": result.last_date,
        "initial_equity_gbp": result.initial_equity_gbp,
        "final_equity_gbp": result.final_equity_gbp,
        "ending_cash_gbp": result.ending_cash_gbp,
        "net_pnl_gbp": result.net_pnl_gbp,
        "decisions": len(result.decisions),
        "entries": len(result.entries),
        "exits": len(result.exits),
        "open_positions": result.open_count,
        "reasons": result.reason_counts(),
    }


def run_identifier(result: ReplayResult) -> str:
    payload = {"summary": run_summary(result),
               "events": [event.as_record() for event in result.events]}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:24]
