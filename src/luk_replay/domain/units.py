"""Explicitly distinguish equities (USD) from spread-bet stakes (GBP/point)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

Number = Union[str, int, float, Decimal]
PENNY = Decimal("0.01")
POINTS_PER_DOLLAR = Decimal("100")
MIN_VOLUME = 10
STEP_VOLUME = 10
MAX_VOLUME = 1_000_000


class UnitError(ValueError):
    """A price or stake does not represent a valid instrument quantity."""


def decimal_of(value: Number, *, name: str = "value") -> Decimal:
    """Decode textual input without propagating binary float approximation."""
    if isinstance(value, bool):
        raise UnitError(f"{name} must be a finite decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise UnitError(f"{name} must be a finite decimal") from exc
    if not number.is_finite():
        raise UnitError(f"{name} must be a finite decimal")
    return number


def quantize_usd(value: Number) -> Decimal:
    number = decimal_of(value, name="USD price")
    if number < 0:
        raise UnitError("USD price cannot be negative")
    if number.as_tuple().exponent < -2:
        raise UnitError("USD price must have at most two decimal places")
    return number.quantize(PENNY)


def to_broker_points(usd: Number) -> Decimal:
    """A $115.04 stock is quoted as 11504 broker points for *.US_SB."""
    return quantize_usd(usd) * POINTS_PER_DOLLAR


def from_broker_points(points: Number) -> Decimal:
    raw = decimal_of(points, name="broker points")
    if raw < 0 or raw != raw.to_integral_value():
        raise UnitError("broker points must be non-negative integral points")
    return (raw / POINTS_PER_DOLLAR).quantize(PENNY)


def stake_for_volume(volume: int) -> Decimal:
    if isinstance(volume, bool) or not isinstance(volume, int):
        raise UnitError("broker volume must be an integer")
    if volume < MIN_VOLUME or volume % STEP_VOLUME != 0 or volume > MAX_VOLUME:
        raise UnitError("broker volume must be a valid step of at least 10")
    return Decimal(volume) / Decimal("100")


def volume_for_stake(stake: Number) -> int:
    amount = decimal_of(stake, name="GBP per point")
    if amount <= 0:
        raise UnitError("GBP per point must be positive")
    volume = amount * Decimal("100")
    if volume != volume.to_integral_value():
        raise UnitError("GBP per point must have penny granularity")
    integer = int(volume)
    stake_for_volume(integer)
    return integer


def risk_gbp(entry_points: Number, stop_points: Number, stake: Number) -> Decimal:
    distance = abs(decimal_of(entry_points) - decimal_of(stop_points))
    amount = decimal_of(stake, name="GBP per point")
    if amount <= 0:
        raise UnitError("GBP per point must be positive")
    return (distance * amount).quantize(PENNY, rounding=ROUND_HALF_UP)


def pnl_gbp(entry_points: Number, exit_points: Number, stake: Number, side: str) -> Decimal:
    sign = Decimal(1) if side == "LONG" else Decimal(-1) if side == "SHORT" else None
    if sign is None:
        raise UnitError("side must be LONG or SHORT")
    return ((decimal_of(exit_points) - decimal_of(entry_points)) * decimal_of(stake)
            * sign).quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Price:
    usd: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "usd", quantize_usd(self.usd))

    @property
    def points(self) -> Decimal:
        return to_broker_points(self.usd)
