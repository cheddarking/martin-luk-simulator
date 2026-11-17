"""Versioned mechanical setup checks with evidence for every outcome."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from luk_replay.domain.events import Decision
from .context import DailyContext
from .reasons import ReasonCode, explain

VERSION = "daily-pullback-v1"


def evaluate_pullback(context: DailyContext | None, *, as_of: datetime,
                      price_usd: Decimal | None = None,
                      zone_slack_pct: Decimal = Decimal("0.35")) -> Decision:
    if as_of.tzinfo is None:
        raise ValueError("decision time requires timezone")
    symbol = context.symbol if context else "UNKNOWN"
    observed = price_usd if price_usd is not None else (
        context.observed_close if context else None)
    evidence: list[str] = []

    def verdict(code: ReasonCode) -> Decision:
        return Decision(as_of, symbol, code == ReasonCode.APPROVED, code.value,
                        explain(code), observed, VERSION, tuple(evidence))

    if context is None or observed is None:
        return verdict(ReasonCode.NO_DATA)
    evidence.append(f"completed daily history: {context.history_count} bars")
    if context.history_count < 50:
        return verdict(ReasonCode.INSUFFICIENT_HISTORY)
    if not context.aligned or not context.rising:
        evidence.append(f"EMA aligned: {context.aligned}, rising: {context.rising}")
        return verdict(ReasonCode.WEAK_TREND)
    if context.zone is None or not context.zone.contains(observed, slack_pct=zone_slack_pct):
        evidence.append(f"price: {observed}; support: {context.zone}")
        return verdict(ReasonCode.NOT_IN_SUPPORT_ZONE)
    if context.avwap is None or abs(observed - context.avwap) / context.avwap > Decimal("0.03"):
        evidence.append(f"AVWAP confluence: {context.avwap}")
        return verdict(ReasonCode.NOT_IN_SUPPORT_ZONE)
    if context.volume_ratio is not None and context.volume_ratio < Decimal("0.6"):
        evidence.append(f"relative volume: {context.volume_ratio}")
        return verdict(ReasonCode.WEAK_VOLUME)
    evidence.extend((f"support: {context.zone.low}-{context.zone.high}",
                     f"AVWAP: {context.avwap}", f"EMA9: {context.ema_9}"))
    return verdict(ReasonCode.APPROVED)
