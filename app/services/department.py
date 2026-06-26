"""Department mapping per spec.

wrong_transfer              → dispute_resolution
payment_failed              → payments_ops
duplicate_payment           → payments_ops
merchant_settlement_delay   → merchant_operations
agent_cash_in_issue         → agent_operations
phishing_or_social_engineering → fraud_risk
refund_request              → low: customer_support | disputed: dispute_resolution | unknown: customer_support
other                       → customer_support
"""
from __future__ import annotations

from app.schemas import CaseType, Department, EvidenceVerdict, Severity


def map_department(
    case_type: CaseType,
    severity: Severity,
    evidence_verdict: EvidenceVerdict,
) -> Department:
    if case_type == CaseType.WRONG_TRANSFER:
        return Department.DISPUTE_RESOLUTION
    if case_type == CaseType.PAYMENT_FAILED:
        return Department.PAYMENTS_OPS
    if case_type == CaseType.DUPLICATE_PAYMENT:
        return Department.PAYMENTS_OPS
    if case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
        return Department.MERCHANT_OPERATIONS
    if case_type == CaseType.AGENT_CASH_IN_ISSUE:
        return Department.AGENT_OPERATIONS
    if case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING:
        return Department.FRAUD_RISK
    if case_type == CaseType.REFUND_REQUEST:
        if evidence_verdict == EvidenceVerdict.INCONSISTENT:
            return Department.DISPUTE_RESOLUTION
        if severity in (Severity.HIGH, Severity.CRITICAL):
            return Department.DISPUTE_RESOLUTION
        return Department.CUSTOMER_SUPPORT
    return Department.CUSTOMER_SUPPORT