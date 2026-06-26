"""Evidence verdict — STEP 5 of the investigation pipeline.

Calibrated against the official sample case pack:
  SAMPLE-01 wrong_transfer consistent        → consistent
  SAMPLE-02 wrong_transfer w/ established    → inconsistent
  SAMPLE-03 payment_failed clear evidence    → consistent
  SAMPLE-04 refund_request clear evidence    → consistent
  SAMPLE-05 phishing empty history           → insufficient_data
  SAMPLE-06 vague complaint                  → insufficient_data
  SAMPLE-07 agent cash-in pending            → consistent
  SAMPLE-08 ambiguous multiple txns          → insufficient_data
  SAMPLE-09 merchant settlement pending      → consistent
  SAMPLE-10 duplicate payment clear          → consistent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.schemas import EvidenceVerdict, TransactionStatus
from app.services import reason_codes as RC
from app.services.complaint_parser import ParsedComplaint
from app.services.matcher import MatchResult


@dataclass
class EvidenceResult:
    verdict: EvidenceVerdict
    confidence: float
    reason_codes: List[str]


def _base_confidence(best: Optional[MatchResult]) -> float:
    if best is None:
        return 0.30
    s = best.score
    return min(0.95, max(0.55, 0.55 + 0.45 * s))


def _has_strong_amount_or_recipient(best: Optional[MatchResult]) -> bool:
    if not best:
        return False
    return best.amount_match == "exact" or best.recipient_match == "exact"


def evaluate_evidence(
    parsed: ParsedComplaint,
    best: Optional[MatchResult],
    transactions_present: bool,
    ambiguity_detected: bool = False,
    established_recipient_count: int = 0,
) -> EvidenceResult:
    """Produce evidence_verdict + confidence + reason codes."""
    reasons: List[str] = []

    # Empty history
    if not transactions_present:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT_DATA,
            confidence=0.30,
            reason_codes=[RC.NO_MATCHING_TRANSACTION, RC.NO_TRANSACTION_HISTORY],
        )

    # Ambiguous match — refuse to pick (SAMPLE-08)
    if ambiguity_detected:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT_DATA,
            confidence=0.65,
            reason_codes=[
                RC.AMBIGUOUS_COMPLAINT,
                "ambiguous_match",
                "needs_clarification",
            ],
        )

    # No transaction matches at all
    if best is None:
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT_DATA,
            confidence=0.35,
            reason_codes=[RC.NO_MATCHING_TRANSACTION, RC.AMBIGUOUS_COMPLAINT],
        )

    base_conf = _base_confidence(best)

    # Established recipient pattern contradicts wrong_transfer claim (SAMPLE-02)
    if established_recipient_count >= 2 and parsed.has_wrong_transfer:
        return EvidenceResult(
            verdict=EvidenceVerdict.INCONSISTENT,
            confidence=min(0.85, base_conf + 0.05),
            reason_codes=best.triggered_reasons
            + ["established_recipient_pattern", "wrong_transfer_claim"],
        )

    # Strong match: amount + time + recipient all align
    if (
        best.amount_match == "exact"
        and best.recipient_match in ("exact", "near")
        and best.time_match in ("exact", "near")
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.95, base_conf + 0.05),
            reason_codes=best.triggered_reasons,
        )

    # Contradiction: payment claimed failed but txn completed/succeeded
    if (
        parsed.has_payment_failed
        and best.status_hint in (
            "status_completed_contradicts_payment_failed_claim",
            "status_success_contradicts_payment_failed_claim",
        )
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.INCONSISTENT,
            confidence=min(0.92, base_conf + 0.05),
            reason_codes=best.triggered_reasons
            + [RC.PAYMENT_REPORTED_FAILED_BUT_SUCCESS],
        )

    # Support: payment failed AND txn status failed AND amount matches
    if (
        parsed.has_payment_failed
        and best.status_hint == "status_failed_aligned_with_complaint"
        and best.amount_match == "exact"
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.93, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.PAYMENT_DEBITED_BUT_FAILED],
        )

    # Wrong transfer — amount exact AND recipient matches counterparty
    if (
        parsed.has_wrong_transfer
        and best.amount_match == "exact"
        and best.recipient_match in ("exact", "near")
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.92, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.WRONG_TRANSFER_DETECTED],
        )

    # Wrong transfer — amount exact + time recent + type match.
    # Recipient won't match because customer sent to wrong number — that's
    # the whole complaint. Evidence supports the claim because a transfer
    # with the stated amount exists in the recent timeframe.
    if (
        parsed.has_wrong_transfer
        and best.amount_match == "exact"
        and best.time_match in ("exact", "near")
        and best.type_match
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.90, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.WRONG_TRANSFER_DETECTED],
        )

    # Wrong transfer — amount exact + time recent (relaxed type check)
    if (
        parsed.has_wrong_transfer
        and best.amount_match == "exact"
        and best.time_match in ("exact", "near")
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.88, base_conf),
            reason_codes=best.triggered_reasons + [RC.WRONG_TRANSFER_DETECTED],
        )

    # Refund with reversed status → consistent
    if (
        parsed.has_refund_request
        and best.status_hint == "status_reversed_aligned_with_refund_request"
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.90, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.REFUND_NOT_RECEIVED],
        )

    # Duplicate confirmed by matcher + amount match
    if (
        parsed.has_duplicate_payment
        and best.amount_match == "exact"
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.93, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.DUPLICATE_DETECTED],
        )

    # Settlement pending aligns with merchant settlement delay
    if (
        parsed.has_merchant_settlement
        and best.amount_match == "exact"
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.92, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.MERCHANT_SETTLEMENT_DELAY_DETECTED],
        )

    # Agent cash-in pending aligns with complaint
    if (
        parsed.has_agent_cash_in
        and best.amount_match == "exact"
    ):
        return EvidenceResult(
            verdict=EvidenceVerdict.CONSISTENT,
            confidence=min(0.88, base_conf + 0.05),
            reason_codes=best.triggered_reasons + [RC.AGENT_CASH_IN_ISSUE_DETECTED],
        )

    # If we only have a weak match
    if not _has_strong_amount_or_recipient(best):
        return EvidenceResult(
            verdict=EvidenceVerdict.INSUFFICIENT_DATA,
            confidence=base_conf * 0.7,
            reason_codes=best.triggered_reasons + [RC.AMBIGUOUS_COMPLAINT],
        )

    # Default: weak evidence support
    return EvidenceResult(
        verdict=EvidenceVerdict.INSUFFICIENT_DATA,
        confidence=base_conf,
        reason_codes=best.triggered_reasons + [RC.AMBIGUOUS_COMPLAINT],
    )