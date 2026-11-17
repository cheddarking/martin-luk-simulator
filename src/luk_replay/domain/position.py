"""Open simulated spread-bet exposure and legal stake transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR

from .units import STEP_VOLUME, risk_gbp, stake_for_volume


@dataclass(frozen=True, slots=True)
class Position:
    position_id: str
    symbol: str
    side: str
    opened_at: datetime
    entry_points: Decimal
    stop_points: Decimal
    volume: int
    target_points: Decimal | None = None
    remaining_volume: int | None = None
    realized_gbp: Decimal = Decimal("0")
    ema_trail_armed: bool = False
    highest_close_points: Decimal | None = None
    entry_session: str | None = None
    trimmed_targets: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None:
            raise ValueError("position requires timezone-aware open")
        if self.side not in {"LONG", "SHORT"}:
            raise ValueError("position side must be LONG or SHORT")
        if self.entry_points <= 0 or self.stop_points <= 0:
            raise ValueError("entry and stop must be positive points")
        if (self.side == "LONG" and self.stop_points >= self.entry_points) or (
                self.side == "SHORT" and self.stop_points <= self.entry_points):
            raise ValueError("protective stop must be beyond entry")
        stake_for_volume(self.volume)
        if self.remaining_volume is not None:
            if self.remaining_volume < 0 or self.remaining_volume > self.volume:
                raise ValueError("remaining stake exceeds initial stake")
            if self.remaining_volume and self.remaining_volume % STEP_VOLUME:
                raise ValueError("remaining stake must use broker volume step")
        if self.target_points is not None and self.target_points <= 0:
            raise ValueError("profit target must be positive")
        if len(set(self.trimmed_targets)) != len(self.trimmed_targets):
            raise ValueError("profit-target levels cannot be trimmed twice")

    @property
    def open_volume(self) -> int:
        return self.volume if self.remaining_volume is None else self.remaining_volume

    @property
    def stake_gbp(self) -> Decimal:
        return stake_for_volume(self.open_volume) if self.open_volume else Decimal()

    @property
    def initial_risk_gbp(self) -> Decimal:
        return risk_gbp(self.entry_points, self.stop_points, stake_for_volume(self.volume))

    @property
    def open_risk_gbp(self) -> Decimal:
        if self.open_volume == 0:
            return Decimal()
        if (self.side == "LONG" and self.stop_points >= self.entry_points) or (
                self.side == "SHORT" and self.stop_points <= self.entry_points):
            return Decimal()
        return risk_gbp(self.entry_points, self.stop_points, self.stake_gbp)

    def can_trim(self, fraction: Decimal) -> bool:
        if fraction <= 0 or fraction >= 1 or self.open_volume <= STEP_VOLUME:
            return False
        requested = Decimal(self.open_volume) * fraction
        return (requested >= STEP_VOLUME and
                self.open_volume - int((requested / STEP_VOLUME).to_integral_value(
                    rounding=ROUND_FLOOR)) * STEP_VOLUME >= STEP_VOLUME)

    def trim_volume(self, fraction: Decimal) -> int:
        if not self.can_trim(fraction):
            raise ValueError("partial trim cannot be represented in broker steps")
        return int((Decimal(self.open_volume) * fraction / STEP_VOLUME).to_integral_value(
            rounding=ROUND_FLOOR)) * STEP_VOLUME

    def after_exit(self, closed_volume: int, realized_pnl: Decimal) -> "Position":
        if closed_volume <= 0 or closed_volume % STEP_VOLUME or closed_volume > self.open_volume:
            raise ValueError("invalid closed stake")
        return replace(self, remaining_volume=self.open_volume - closed_volume,
                       realized_gbp=self.realized_gbp + realized_pnl)

    def mark_trim(self, multiple: int) -> "Position":
        if multiple not in (3, 5):
            raise ValueError("only 3R and 5R target levels are supported")
        if multiple in self.trimmed_targets:
            raise ValueError("this R target was already trimmed")
        return replace(self, trimmed_targets=(*self.trimmed_targets, multiple))

    def trail_to(self, new_stop_points: Decimal) -> "Position":
        if self.side == "LONG" and new_stop_points < self.stop_points:
            raise ValueError("long protective stop cannot move backwards")
        if self.side == "SHORT" and new_stop_points > self.stop_points:
            raise ValueError("short protective stop cannot move backwards")
        return replace(self, stop_points=new_stop_points)
