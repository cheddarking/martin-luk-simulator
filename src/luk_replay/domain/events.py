"""Decision and execution events form a deterministic audit record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Mapping


class EventKind(StrEnum):
    BAR_COMPLETED = "BAR_COMPLETED"
    SETUP = "SETUP"
    REJECTION = "REJECTION"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    STOP = "STOP"
    TRIM = "TRIM"
    EXIT = "EXIT"
    CASH = "CASH"
    RISK = "RISK"
    SESSION = "SESSION"


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    sequence: int
    as_of: datetime
    kind: EventKind
    symbol: str
    reason: str
    details: Mapping[str, str] = field(default_factory=dict)
    strategy_version: str = "daily-pullback-v1"

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence must be nonnegative")
        if self.as_of.tzinfo is None:
            raise ValueError("event timestamp requires timezone")
        if not self.strategy_version:
            raise ValueError("strategy version is required")

    def normalized_timestamp(self) -> str:
        return self.as_of.astimezone(timezone.utc).isoformat()

    def as_record(self) -> dict[str, object]:
        return {"sequence": self.sequence, "as_of": self.normalized_timestamp(),
                "kind": self.kind.value, "symbol": self.symbol, "reason": self.reason,
                "details": dict(sorted(self.details.items())),
                "strategy_version": self.strategy_version}


@dataclass(frozen=True, slots=True)
class Decision:
    as_of: datetime
    symbol: str
    accepted: bool
    reason: str
    description: str
    observed_close_usd: Decimal | None
    strategy_version: str
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("decision requires an aware timestamp")
        if not self.reason:
            raise ValueError("every decision needs a reason")

    def as_event(self, sequence: int) -> ReplayEvent:
        return ReplayEvent(sequence, self.as_of,
                           EventKind.SETUP if self.accepted else EventKind.REJECTION,
                           self.symbol, self.reason,
                           {"close_usd": str(self.observed_close_usd or ""),
                            "explanation": self.description,
                            "evidence": "; ".join(self.evidence)}, self.strategy_version)
