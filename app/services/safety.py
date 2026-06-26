"""Safety engine — calibrated against the official sample case pack.

Per-sample human_review_required expectations:
  SAMPLE-01 wrong_transfer clear         → True
  SAMPLE-02 wrong_transfer inconsistent → True
  SAMPLE-03 payment_failed clear         → False (auto-reversal SLA)
  SAMPLE-04 refund simple                → False (merchant policy)
  SAMPLE-05 phishing                     → True
  SAMPLE-06 vague / insufficient         → False
  SAMPLE-07 agent cash-in pending        → True
  SAMPLE-08 ambiguous                    → False (need clarification)
  SAMPLE-09 merchant settlement          → False (standard SLA)
  SAMPLE-10 duplicate payment            → True (biller verification)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.config import get_settings
from app.schemas import CaseType, EvidenceVerdict, Severity
from app.services import reason_codes as RC
from app.services.complaint_parser import ParsedComplaint


@dataclass
class SafetyAssessment:
    risk_flags: List[str]
    requires_human_review: bool
    reason_codes: List[str]


def assess_safety(
    parsed: ParsedComplaint,
    case_type: CaseType,
    severity: Severity,
    evidence_verdict: EvidenceVerdict,
    has_match: bool,
    ambiguity_detected: bool = False,
    established_recipient_count: int = 0,
    user_type: str = "customer",
) -> SafetyAssessment:
    """Compute risk flags + human-review decision."""
    settings = get_settings()
    flags: List[str] = []
    reasons: List[str] = []

    # Start with default — depends on case
    human_review = False

    # Injection always escalates
    if parsed.injection_detected:
        flags.append("prompt_injection_detected")
        reasons.append(RC.PROMPT_INJECTION_DETECTED)
        human_review = True

    # Phishing — critical, always human review
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        flags.append("phishing_risk")
        reasons.append(RC.PHISHING_DETECTED)
        human_review = True
        return SafetyAssessment(
            risk_flags=list(dict.fromkeys(flags)),
            requires_human_review=True,
            reason_codes=list(dict.fromkeys(reasons)),
        )

    # Fraud keywords present — review if substantive
    if parsed.fraud_keywords:
        flags.append("fraud_keywords_present")

    # Inconsistent evidence → review
    if evidence_verdict == EvidenceVerdict.INCONSISTENT:
        flags.append("contradictory_evidence")
        human_review = True
        reasons.append("evidence_inconsistent")

    # Established recipient pattern → review (SAMPLE-02)
    if established_recipient_count >= 2:
        flags.append("established_recipient_pattern")
        reasons.append("established_recipient_pattern")
        human_review = True

    # Case-specific human-review rules
    if case_type == CaseType.WRONG_TRANSFER:
        # SAMPLE-01: clear wrong_transfer → review
        if severity in (Severity.HIGH, Severity.CRITICAL):
            human_review = True
            reasons.append("dispute_initiated")
        elif severity == Severity.MEDIUM and evidence_verdict == EvidenceVerdict.INSUFFICIENT_DATA:
            # SAMPLE-08 ambiguous: no review yet
            human_review = False
        elif severity == Severity.MEDIUM:
            # SAMPLE-02 inconsistent → review (already set above)
            human_review = True

    elif case_type == CaseType.PAYMENT_FAILED:
        # SAMPLE-03: clear payment_failed → no review (auto-reversal)
        human_review = False
        reasons.append("payment_failed")
        reasons.append("potential_balance_deduction")

    elif case_type == CaseType.REFUND_REQUEST:
        # SAMPLE-04: simple refund → no review
        human_review = False
        reasons.append("refund_request")
        reasons.append("merchant_policy_dependent")

    elif case_type == CaseType.DUPLICATE_PAYMENT:
        # SAMPLE-10: duplicate → review (biller verification)
        human_review = True
        reasons.append("duplicate_payment")
        reasons.append("biller_verification_required")

    elif case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        # SAMPLE-09: settlement → no review (standard SLA)
        human_review = False
        reasons.append("merchant_settlement")
        reasons.append("delay")
        reasons.append("pending")

    elif case_type == CaseType.AGENT_CASH_IN_ISSUE:
        # SAMPLE-07: agent cash-in pending → review
        human_review = True
        reasons.append("agent_cash_in")
        reasons.append("pending_transaction")
        reasons.append("agent_ops")

    elif case_type == CaseType.OTHER:
        # SAMPLE-06: vague → no review, ask for clarification
        human_review = False
        reasons.append("vague_complaint")
        reasons.append("needs_clarification")

    # Ambiguity — explicitly NOT yet human review
    if ambiguity_detected:
        reasons.append("ambiguous_match")
        reasons.append("needs_clarification")
        human_review = False

    # Critical severity → always review
    if severity == Severity.CRITICAL and case_type != CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        flags.append("critical_severity")
        human_review = True

    # Large amount → review
    if parsed.amount is not None and parsed.amount >= settings.large_amount_threshold:
        flags.append("high_value_transaction")
        human_review = True

    # No match → review (we have nothing to act on) — EXCEPT for vague
    # complaints, where we just ask for clarification first. AND exception
    # for injection attempts which always need review.
    if (
        not has_match
        and not ambiguity_detected
        and case_type != CaseType.OTHER
    ) or parsed.injection_detected:
        if not has_match and case_type != CaseType.OTHER:
            flags.append("no_matching_transaction")
        human_review = True

    # Deduplicate while preserving order
    flags = list(dict.fromkeys(flags))
    reasons = list(dict.fromkeys(reasons))

    return SafetyAssessment(
        risk_flags=flags,
        requires_human_review=human_review,
        reason_codes=reasons,
    )