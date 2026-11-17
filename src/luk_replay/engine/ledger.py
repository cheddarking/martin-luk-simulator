"""Double-entry cash / realized P&L ledger: each posting sums to zero."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from .fills import ExitFill


@dataclass(frozen=True, slots=True)
class Posting:
    transaction_id: str
    as_of: datetime
    account: str
    amount_gbp: Decimal
    memo: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("posting timestamp requires timezone")
        if self.amount_gbp.as_tuple().exponent < -2:
            raise ValueError("posting must be denominated to GBP pence")


@dataclass(slots=True)
class Ledger:
    entries: list[Posting] = field(default_factory=list)
    committed_transactions: set[str] = field(default_factory=set)

    def record(self, transaction_id: str, posts: Iterable[Posting]) -> None:
        batch = tuple(posts)
        if not batch:
            raise ValueError("empty transaction is not permitted")
        if transaction_id in self.committed_transactions:
            raise ValueError("duplicate ledger transaction")
        if any(post.transaction_id != transaction_id for post in batch):
            raise ValueError("mixed transaction identifiers")
        if sum((post.amount_gbp for post in batch), Decimal()) != Decimal():
            raise ValueError("unbalanced ledger transaction")
        self.entries.extend(batch)
        self.committed_transactions.add(transaction_id)

    def record_exit(self, fill: ExitFill) -> None:
        identifier = (f"exit:{fill.position_id}:{fill.filled_at.isoformat()}:"
                      f"{fill.volume}:{fill.reason}")
        self.record(identifier, (
            Posting(identifier, fill.filled_at, "CASH", fill.pnl_gbp, fill.reason),
            Posting(identifier, fill.filled_at, "REALIZED_PNL", -fill.pnl_gbp, fill.reason),
        ))

    def balance(self) -> Decimal:
        return sum((entry.amount_gbp for entry in self.entries), Decimal())

    def cash_change(self) -> Decimal:
        return sum((e.amount_gbp for e in self.entries if e.account == "CASH"), Decimal())

    def realized_pnl(self) -> Decimal:
        return -sum((e.amount_gbp for e in self.entries if e.account == "REALIZED_PNL"),
                    Decimal())

    def verify(self) -> None:
        if self.balance() != Decimal():
            raise ValueError("ledger is not balanced")
        for identifier in self.committed_transactions:
            total = sum((p.amount_gbp for p in self.entries if p.transaction_id == identifier),
                        Decimal())
            if total != Decimal():
                raise ValueError(f"transaction {identifier} is not balanced")
