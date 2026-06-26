"""Case type classifier.

Priority order — phishing first (safety), then wrong_transfer (high severity),
then payment_failed, duplicate, refund, merchant, agent, other.
"""
from __future__ import annotations

from typing import List

from app.schemas import CaseType
from app.services import reason_codes as RC
from app.services.complaint_parser import ParsedComplaint
from app.services.matcher import MatcherOutput


def classify_case(parsed: ParsedComplaint, matcher_out: MatcherOutput) -> tuple[CaseType, List[str]]:
    """Return (case_type, reason_codes)."""
    reasons: List[str] = []

    # 1) Safety first — phishing OR prompt-injection always wins.
    if parsed.has_phishing_signal or parsed.injection_detected:
        reasons.append(RC.PHISHING_DETECTED)
        return CaseType.PHISHING_OR_SOCIAL_ENGINEERING, reasons

    # 2) Wrong transfer — strong intent signal
    if parsed.has_wrong_transfer:
        reasons.append(RC.WRONG_TRANSFER_DETECTED)
        return CaseType.WRONG_TRANSFER, reasons

    # 3) Duplicate payment (matcher detection also qualifies)
    if parsed.has_duplicate_payment or matcher_out.duplicates:
        reasons.append(RC.DUPLICATE_DETECTED)
        return CaseType.DUPLICATE_PAYMENT, reasons

    # 4) Payment failed
    if parsed.has_payment_failed:
        reasons.append(RC.PAYMENT_DEBITED_BUT_FAILED)
        return CaseType.PAYMENT_FAILED, reasons

    # 5) Agent cash-in issue (check before merchant — agent signals are
    # usually more specific than generic merchant mentions)
    if parsed.has_agent_cash_in:
        reasons.append(RC.AGENT_CASH_IN_ISSUE_DETECTED)
        return CaseType.AGENT_CASH_IN_ISSUE, reasons

    # 6) Refund request — wins over merchant_settlement when the customer
    # explicitly says "refund" (e.g. change-of-mind merchant payment → refund)
    if parsed.has_refund_request:
        reasons.append(RC.REFUND_NOT_RECEIVED)
        return CaseType.REFUND_REQUEST, reasons

    # 7) Merchant settlement delay (only if no refund intent)
    if parsed.has_merchant_settlement:
        reasons.append(RC.MERCHANT_SETTLEMENT_DELAY_DETECTED)
        return CaseType.MERCHANT_SETTLEMENT_DELAY, reasons

    # 8) Nothing matched
    reasons.append(RC.NO_CLEAR_INTENT)
    return CaseType.OTHER, reasons