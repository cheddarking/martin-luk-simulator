"""Process and outcome diagnostics remain separate in a strategy replay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from .fills import ExitFill
from .portfolio import PortfolioSnapshot
from .replay import ReplayResult


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    initial_gbp: Decimal
    final_gbp: Decimal
    realized_gbp: Decimal
    unrealized_gbp: Decimal
    peak_gbp: Decimal
    max_drawdown_gbp: Decimal
    max_drawdown_pct: Decimal
    completed_trades: int
    winners: int
    losers: int
    flat: int
    average_win_gbp: Decimal | None
    average_loss_gbp: Decimal | None
    winning_fraction: Decimal | None


def drawdowns(snapshots: Sequence[PortfolioSnapshot]) -> tuple[Decimal, ...]:
    peak: Decimal | None = None
    output: list[Decimal] = []
    for item in snapshots:
        peak = item.equity_gbp if peak is None else max(peak, item.equity_gbp)
        output.append(peak - item.equity_gbp)
    return tuple(output)


def summarize(result: ReplayResult) -> PerformanceSummary:
    curve = result.snapshots
    peak = max((s.equity_gbp for s in curve), default=result.initial_equity_gbp)
    loss = max(drawdowns(curve), default=Decimal())
    fills = result.exits
    wins = [f.pnl_gbp for f in fills if f.pnl_gbp > 0]
    losses = [f.pnl_gbp for f in fills if f.pnl_gbp < 0]
    flat = sum(f.pnl_gbp == 0 for f in fills)
    realized = result.ending_cash_gbp - result.initial_equity_gbp
    unrealized = result.final_equity_gbp - result.ending_cash_gbp
    return PerformanceSummary(
        result.initial_equity_gbp, result.final_equity_gbp, realized, unrealized,
        peak, loss,
        loss / peak * 100 if peak else Decimal(), len(fills), len(wins),
        len(losses), flat,
        sum(wins, Decimal()) / len(wins) if wins else None,
        sum(losses, Decimal()) / len(losses) if losses else None,
        Decimal(len(wins)) / len(fills) if fills else None,
    )


def reason_breakdown(result: ReplayResult) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(result.reason_counts().items(), key=lambda item: (-item[1], item[0])))


def equity_series(snapshots: Sequence[PortfolioSnapshot]) -> tuple[tuple[str, Decimal], ...]:
    return tuple((s.as_of.isoformat(), s.equity_gbp) for s in snapshots)
