"""Strategy reasons and broker-specific minimum stake constraint."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from luk_replay.domain.settings import RiskSettings
from luk_replay.strategy.risk import assess_risk
from luk_replay.strategy.reasons import ReasonCode


NY = ZoneInfo("America/New_York")


def test_rejects_unexpressible_minimum_stake_risk_with_reason() -> None:
    decision = assess_risk(
        entry_usd=Decimal("100.00"), stop_usd=Decimal("98.00"),
        settings=RiskSettings(equity_gbp=Decimal("1000")),
        as_of=datetime(2026, 11, 16, 9, 35, tzinfo=NY),
    )
    assert decision.allowed is False
    assert decision.reason == ReasonCode.SKIPPED_SIZING
    assert decision.minimum_risk_gbp == Decimal("20.00")
    assert decision.budget_gbp == Decimal("5.00")
    assert decision.strategy_version
    assert decision.as_of.tzinfo is not None


def test_expressible_risk_respects_step_size() -> None:
    decision = assess_risk(
        entry_usd=Decimal("100.00"), stop_usd=Decimal("98.00"),
        settings=RiskSettings(equity_gbp=Decimal("20000")),
        as_of=datetime(2026, 11, 16, 9, 35, tzinfo=NY),
    )
    assert decision.allowed is True
    assert decision.volume % 10 == 0
    assert decision.risk_gbp <= decision.budget_gbp
    assert decision.risk_gbp >= decision.minimum_risk_gbp


def test_notional_cap_downsizes_when_minimum_stake_fits() -> None:
    decision = assess_risk(
        entry_usd=Decimal("100.00"), stop_usd=Decimal("99.00"),
        settings=RiskSettings(equity_gbp=Decimal("10000")),
        as_of=datetime(2026, 11, 16, 9, 35, tzinfo=NY),
    )
    assert decision.allowed is True
    assert decision.volume == 30
    assert decision.stake_gbp_per_point == Decimal("0.30")


def test_wide_stop_rejected_before_sizing() -> None:
    decision = assess_risk(
        entry_usd=Decimal("100.00"), stop_usd=Decimal("96.00"),
        settings=RiskSettings(), as_of=datetime(2026, 11, 16, 9, 35, tzinfo=NY),
    )
    assert decision.reason == ReasonCode.STOP_TOO_WIDE
    assert decision.volume == 0
