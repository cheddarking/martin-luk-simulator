"""Stable rule and explanation codes; every skip has an inspectable reason."""

from __future__ import annotations

from enum import StrEnum


class ReasonCode(StrEnum):
    APPROVED = "APPROVED"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    NOT_IN_SESSION = "NOT_IN_SESSION"
    NOT_IN_SUPPORT_ZONE = "NOT_IN_SUPPORT_ZONE"
    WEAK_TREND = "WEAK_TREND"
    WEAK_VOLUME = "WEAK_VOLUME"
    STOP_TOO_WIDE = "STOP_TOO_WIDE"
    STOP_TOO_TIGHT = "STOP_TOO_TIGHT"
    STOP_INVALID_SIDE = "STOP_INVALID_SIDE"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    SKIPPED_SIZING = "SKIPPED_SIZING"
    NOTIONAL_CAP = "NOTIONAL_CAP"
    OPEN_RISK_CAP = "OPEN_RISK_CAP"
    GAP_RISK_EXCEEDED = "GAP_RISK_EXCEEDED"
    DAILY_LOSS_CAP = "DAILY_LOSS_CAP"
    MAX_POSITIONS = "MAX_POSITIONS"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    NO_DATA = "NO_DATA"
    MISSING_QUOTE = "MISSING_QUOTE"
    MARKET_CLOSED = "MARKET_CLOSED"
    GAP_THROUGH_STOP = "GAP_THROUGH_STOP"
    STOP_FILLED = "STOP_FILLED"
    TARGET_FILLED = "TARGET_FILLED"
    EOD_EMA_EXIT = "EOD_EMA_EXIT"
    ENTRY_DAY_TRAIL_SKIPPED = "ENTRY_DAY_TRAIL_SKIPPED"
    INVALID_INPUT = "INVALID_INPUT"


DESCRIPTIONS: dict[ReasonCode, str] = {
    ReasonCode.APPROVED: "The observed setup passed the defined mechanical checks.",
    ReasonCode.INSUFFICIENT_HISTORY: "The rule needs more completed historical bars.",
    ReasonCode.NOT_IN_SESSION: "This observation falls outside regular exchange hours.",
    ReasonCode.NOT_IN_SUPPORT_ZONE: "Price has not tested the computed support zone.",
    ReasonCode.WEAK_TREND: "The EMA context does not support this long setup.",
    ReasonCode.WEAK_VOLUME: "Volume evidence does not meet the rule's threshold.",
    ReasonCode.STOP_TOO_WIDE: "Stop distance exceeds the soft or hard stop limit.",
    ReasonCode.STOP_TOO_TIGHT: "Stop requires padding to the minimum distance.",
    ReasonCode.STOP_INVALID_SIDE: "Stop is not on the protective side of entry.",
    ReasonCode.SPREAD_TOO_WIDE: "Observed spread exceeds the maximum percentage.",
    ReasonCode.SKIPPED_SIZING: "The minimum broker stake exceeds the allowed risk.",
    ReasonCode.NOTIONAL_CAP: "The proposed stake exceeds the equity-based notional cap.",
    ReasonCode.OPEN_RISK_CAP: "Total non-breakeven risk is already at the cap.",
    ReasonCode.GAP_RISK_EXCEEDED: "The next-open gap makes the fixed stake too risky to enter.",
    ReasonCode.DAILY_LOSS_CAP: "Trading is paused after the daily loss cap.",
    ReasonCode.MAX_POSITIONS: "The maximum number of concurrent positions is reached.",
    ReasonCode.DUPLICATE_SIGNAL: "This setup already produced an accepted signal.",
    ReasonCode.NO_DATA: "No completed bar is available for this decision.",
    ReasonCode.MISSING_QUOTE: "A price/spread quote needed for execution is absent.",
    ReasonCode.MARKET_CLOSED: "The market is not open at this timestamp.",
    ReasonCode.GAP_THROUGH_STOP: "The session opened beyond the stop; the gap price is used.",
    ReasonCode.STOP_FILLED: "The protective stop was reached.",
    ReasonCode.TARGET_FILLED: "A predefined partial target was reached.",
    ReasonCode.EOD_EMA_EXIT: "The close was below the active end-of-day EMA trail.",
    ReasonCode.ENTRY_DAY_TRAIL_SKIPPED: "The EMA trail is not armed on the entry day.",
    ReasonCode.INVALID_INPUT: "The supplied price or quantity is invalid.",
}


def explain(code: ReasonCode | str) -> str:
    try:
        return DESCRIPTIONS[ReasonCode(code)]
    except (ValueError, KeyError):
        return "No explanation is registered for this decision code."
