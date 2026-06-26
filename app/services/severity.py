"""Severity engine — calibrated against the official sample case pack.

Reference points from the official samples:
  SAMPLE-01 wrong_transfer (consistent)        → high
  SAMPLE-02 wrong_transfer (inconsistent)       → medium
  SAMPLE-03 payment_failed (consistent)        → high
  SAMPLE-04 refund_request (consistent, simple)→ low
  SAMPLE-05 phishing                           → critical
  SAMPLE-06 other / vague                      → low
  SAMPLE-07 agent_cash_in (pending)            → high
  SAMPLE-08 wrong_transfer (insufficient_data) → medium
  SAMPLE-09 merchant_settlement_delay          → medium
  SAMPLE-10 duplicate_payment                  → high
"""
from __future__ import annotations

from typing import List

from app.config import get_settings
from app.schemas import CaseType, Severity
from app.services import reason_codes as RC
from app.services.complaint_parser import ParsedComplaint


def determine_severity(
    parsed: ParsedComplaint,
    case_type: CaseType,
    evidence_verdict_is_contradictory: bool,
    evidence_verdict_is_insufficient: bool = False,
) -> tuple[Severity, List[str]]:
    """Return (severity, reason_codes)."""
    settings = get_settings()
    reasons: List[str] = []
    amount = parsed.amount or 0.0

    # CRITICAL — phishing / social engineering
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        reasons.append(RC.PHISHING_DETECTED)
        if amount >= settings.large_amount_threshold:
            reasons.append(RC.LARGE_AMOUNT_FLAG)
        return Severity.CRITICAL, reasons

    # CRITICAL — critical amount with fraud keywords
    if amount >= settings.critical_amount_threshold:
        reasons.append(RC.CRITICAL_AMOUNT_FLAG)
        return Severity.CRITICAL, reasons

    # HIGH — wrong transfer
    if case_type == CaseType.WRONG_TRANSFER:
        if amount >= settings.large_amount_threshold:
            reasons.append(RC.LARGE_AMOUNT_FLAG)
            reasons.append(RC.WRONG_TRANSFER_DETECTED)
            return Severity.CRITICAL, reasons
        if evidence_verdict_is_contradictory:
            # SAMPLE-02: established recipient pattern → medium
            reasons.append(RC.WRONG_TRANSFER_DETECTED)
            reasons.append("established_recipient_pattern")
            return Severity.MEDIUM, reasons
        if evidence_verdict_is_insufficient:
            # SAMPLE-08: ambiguous → medium
            reasons.append(RC.WRONG_TRANSFER_DETECTED)
            return Severity.MEDIUM, reasons
        # SAMPLE-01 consistent → high
        reasons.append(RC.WRONG_TRANSFER_DETECTED)
        return Severity.HIGH, reasons

    # HIGH — payment_failed (per SAMPLE-03)
    if case_type == CaseType.PAYMENT_FAILED:
        reasons.append(RC.PAYMENT_DEBITED_BUT_FAILED)
        if amount >= settings.large_amount_threshold:
            reasons.append(RC.LARGE_AMOUNT_FLAG)
        return Severity.HIGH, reasons

    # HIGH — duplicate payment (per SAMPLE-10)
    if case_type == CaseType.DUPLICATE_PAYMENT:
        reasons.append(RC.DUPLICATE_DETECTED)
        return Severity.HIGH, reasons

    # HIGH — agent cash-in issue (per SAMPLE-07)
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return Severity.HIGH, reasons

    # MEDIUM — merchant settlement delay (per SAMPLE-09)
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        reasons.append(RC.MERCHANT_SETTLEMENT_DELAY_DETECTED)
        return Severity.MEDIUM, reasons

    # LOW — refund request, simple (per SAMPLE-04)
    # Only escalate if disputed/inconsistent or large amount.
    if case_type == CaseType.REFUND_REQUEST:
        reasons.append(RC.REFUND_NOT_RECEIVED)
        if evidence_verdict_is_contradictory:
            return Severity.MEDIUM, reasons
        if amount >= settings.large_amount_threshold:
            reasons.append(RC.LARGE_AMOUNT_FLAG)
            return Severity.MEDIUM, reasons
        return Severity.LOW, reasons

    # LOW — other / vague (per SAMPLE-06)
    if case_type == CaseType.OTHER:
        reasons.append(RC.AMBIGUOUS_COMPLAINT)
        return Severity.LOW, reasons

    # Default fallback
    reasons.append(RC.AMBIGUOUS_COMPLAINT)
    return Severity.LOW, reasons