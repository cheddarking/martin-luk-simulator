"""Signal creation is pure and deduplicated by strategy/time/symbol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from luk_replay.domain.events import Decision
from .reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class TradeSignal:
    signal_id: str
    as_of: datetime
    symbol: str
    entry_usd: Decimal
    stop_usd: Decimal
    reason: str
    strategy_version: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("signal time requires timezone")
        if self.stop_usd >= self.entry_usd:
            raise ValueError("long stop must be below entry")


def signal_from_decision(decision: Decision, *, stop_usd: Decimal,
                         existing: Iterable[str] = ()) -> TradeSignal | None:
    if not decision.accepted or decision.observed_close_usd is None:
        return None
    key = (f"{decision.strategy_version}:{decision.symbol}:"
           f"{decision.as_of.isoformat()}")
    if key in existing:
        return None
    return TradeSignal(key, decision.as_of, decision.symbol,
                       decision.observed_close_usd, stop_usd,
                       decision.reason, decision.strategy_version)


def deduplicate_signals(signals: Iterable[TradeSignal]) -> tuple[TradeSignal, ...]:
    found: dict[str, TradeSignal] = {}
    for signal in signals:
        if signal.signal_id not in found:
            found[signal.signal_id] = signal
    return tuple(found.values())
