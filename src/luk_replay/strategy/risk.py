"""Mechanical, auditable GBP spread-bet risk and stake gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR

from luk_replay.domain.settings import RiskSettings
from luk_replay.domain.units import (MIN_VOLUME, STEP_VOLUME, decimal_of, risk_gbp,
                                     stake_for_volume, to_broker_points)
from .reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class RiskDecision:
    allowed: bool
    reason: ReasonCode
    as_of: datetime
    strategy_version: str
    budget_gbp: Decimal
    minimum_risk_gbp: Decimal
    risk_gbp: Decimal
    volume: int
    stake_gbp_per_point: Decimal
    entry_points: Decimal
    stop_points: Decimal
    stop_padded: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("risk decision time requires timezone")
        if self.allowed and self.volume < MIN_VOLUME:
            raise ValueError("accepted risk decision needs expressible stake")
        if not self.allowed and self.volume:
            raise ValueError("rejected risk decision cannot reserve broker stake")


def assess_risk(
    *, entry_usd: Decimal, stop_usd: Decimal, settings: RiskSettings,
    as_of: datetime, strategy_version: str = "daily-pullback-v1",
    spread_pct: Decimal = Decimal("0"), open_risk_gbp: Decimal = Decimal("0"),
    realized_loss_today_gbp: Decimal = Decimal("0"), open_positions: int = 0,
    cap_notional_pct: Decimal | None = None, adr_usd: Decimal | None = None,
) -> RiskDecision:
    """Return a decision and exact reason, never quietly force an oversized trade.

    Caller supplies broker-quote spread from a historical source when possible.
    When prices are OHLC only, the simulator's default spread is an assumption.
    """
    entry = decimal_of(entry_usd, name="entry")
    stop = decimal_of(stop_usd, name="stop")
    spread = decimal_of(spread_pct, name="spread")
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    if entry <= 0 or stop <= 0 or spread < 0:
        raise ValueError("entry, stop and spread must be valid positive inputs")
    budget = (settings.equity_gbp * settings.risk_pct / 100).quantize(Decimal("0.01"))
    # For a long setup the stop must be strictly below entry.
    points = to_broker_points(entry)
    stop_points = to_broker_points(stop)
    min_risk = risk_gbp(points, stop_points, stake_for_volume(MIN_VOLUME))

    def reject(code: ReasonCode, detail: str = "", padded: bool = False) -> RiskDecision:
        return RiskDecision(False, code, as_of, strategy_version, budget, min_risk,
                            Decimal(), 0, Decimal(), points, stop_points, padded, detail)

    if stop >= entry:
        return reject(ReasonCode.STOP_INVALID_SIDE)
    distance_pct = (entry - stop) / entry * 100
    if distance_pct > settings.soft_max_stop_pct or distance_pct > settings.hard_max_stop_pct:
        return reject(ReasonCode.STOP_TOO_WIDE)
    if adr_usd is not None and adr_usd > 0 and (entry - stop) >= adr_usd / 2:
        return reject(ReasonCode.STOP_TOO_WIDE, "stop reaches at least half of ADR")
    if spread > settings.max_spread_pct:
        return reject(ReasonCode.SPREAD_TOO_WIDE)
    if open_positions >= settings.max_positions:
        return reject(ReasonCode.MAX_POSITIONS)
    if realized_loss_today_gbp >= settings.equity_gbp * settings.max_daily_loss_pct / 100:
        return reject(ReasonCode.DAILY_LOSS_CAP)
    if open_risk_gbp >= settings.equity_gbp * settings.max_open_risk_pct / 100:
        return reject(ReasonCode.OPEN_RISK_CAP)
    if min_risk > budget * Decimal("1.25"):
        return reject(ReasonCode.SKIPPED_SIZING, "minimum lot risks more than 125% of budget")

    available = min(budget, settings.equity_gbp * settings.max_open_risk_pct / 100
                    - open_risk_gbp)
    if available <= 0:
        return reject(ReasonCode.OPEN_RISK_CAP)
    volume = int((available / max(Decimal("0.01"), min_risk) * MIN_VOLUME
                  / STEP_VOLUME).to_integral_value(rounding=ROUND_FLOOR)) * STEP_VOLUME
    volume = max(MIN_VOLUME, volume)
    notional_cap = (settings.large_cap_max_notional_pct if cap_notional_pct is None
                    else cap_notional_pct)
    max_notional_gbp = settings.equity_gbp * notional_cap / 100
    volume_by_notional = int((max_notional_gbp / points * 100 / STEP_VOLUME)
                             .to_integral_value(rounding=ROUND_FLOOR)) * STEP_VOLUME
    if volume_by_notional < MIN_VOLUME:
        return reject(ReasonCode.NOTIONAL_CAP, "even the minimum stake exceeds notional cap")
    volume = min(volume, volume_by_notional)
    stake = stake_for_volume(volume)
    actual_risk = risk_gbp(points, stop_points, stake)
    if actual_risk + open_risk_gbp > settings.equity_gbp * settings.max_open_risk_pct / 100:
        return reject(ReasonCode.OPEN_RISK_CAP)
    return RiskDecision(True, ReasonCode.APPROVED, as_of, strategy_version, budget,
                        min_risk, actual_risk, volume, stake, points, stop_points,
                        False, "mechanical risk constraints passed")
