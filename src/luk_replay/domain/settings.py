"""Immutable model settings: explicitly separate hard limits from parameters."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class RiskSettings:
    equity_gbp: Decimal = Decimal("10000")
    risk_pct: Decimal = Decimal("0.50")
    max_open_risk_pct: Decimal = Decimal("2.00")
    max_daily_loss_pct: Decimal = Decimal("2.00")
    soft_max_stop_pct: Decimal = Decimal("3.00")
    hard_max_stop_pct: Decimal = Decimal("5.00")
    max_spread_pct: Decimal = Decimal("0.25")
    max_positions: int = 8
    large_cap_max_notional_pct: Decimal = Decimal("30")
    small_cap_max_notional_pct: Decimal = Decimal("20")

    def __post_init__(self) -> None:
        if self.equity_gbp <= 0:
            raise ValueError("equity must be positive")
        if not Decimal("0") < self.risk_pct <= Decimal("0.75"):
            raise ValueError("risk must be within 0–0.75%")
        if self.soft_max_stop_pct > self.hard_max_stop_pct:
            raise ValueError("soft stop cannot exceed hard stop")
        if self.max_positions < 1:
            raise ValueError("must permit at least one position")


@dataclass(frozen=True, slots=True)
class ReplaySettings:
    initial_equity_gbp: Decimal = Decimal("10000")
    default_spread_pct: Decimal = Decimal("0.05")
    slippage_points: Decimal = Decimal("0")
    conservative_same_bar: bool = True
    allow_shorts: bool = False
    strategy_version: str = "daily-pullback-v1"

    def __post_init__(self) -> None:
        if self.initial_equity_gbp <= 0:
            raise ValueError("initial equity must be positive")
        if self.default_spread_pct < 0 or self.slippage_points < 0:
            raise ValueError("spread and slippage cannot be negative")
        if not self.strategy_version.strip():
            raise ValueError("strategy version is required")
