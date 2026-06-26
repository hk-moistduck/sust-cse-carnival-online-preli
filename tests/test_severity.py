"""Severity + department tests — calibrated against the official samples."""
from app.schemas import (
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
)
from app.services.complaint_parser import parse_complaint
from app.services.department import map_department
from app.services.severity import determine_severity


def test_phishing_is_critical():
    p = parse_complaint("They asked for my OTP.")
    sev, _ = determine_severity(p, CaseType.PHISHING_OR_SOCIAL_ENGINEERING, False)
    assert sev == Severity.CRITICAL


def test_wrong_transfer_consistent_is_high():
    """SAMPLE-01: consistent wrong transfer → high."""
    p = parse_complaint("I sent 5000 taka to wrong number.")
    sev, _ = determine_severity(p, CaseType.WRONG_TRANSFER, False)
    assert sev == Severity.HIGH


def test_wrong_transfer_inconsistent_is_medium():
    """SAMPLE-02: inconsistent wrong transfer → medium."""
    p = parse_complaint("I sent 2000 to wrong person.")
    sev, _ = determine_severity(p, CaseType.WRONG_TRANSFER, evidence_verdict_is_contradictory=True)
    assert sev == Severity.MEDIUM


def test_wrong_transfer_insufficient_is_medium():
    """SAMPLE-08: insufficient wrong transfer → medium."""
    p = parse_complaint("I sent 1000 to my brother.")
    sev, _ = determine_severity(p, CaseType.WRONG_TRANSFER,
                                 evidence_verdict_is_contradictory=False,
                                 evidence_verdict_is_insufficient=True)
    assert sev == Severity.MEDIUM


def test_payment_failed_consistent_is_high():
    """SAMPLE-03: consistent payment_failed → high."""
    p = parse_complaint("Payment failed but money deducted 1200 taka.")
    sev, _ = determine_severity(p, CaseType.PAYMENT_FAILED, False)
    assert sev == Severity.HIGH


def test_refund_simple_is_low():
    """SAMPLE-04: simple refund_request → low."""
    p = parse_complaint("I paid 500 taka to merchant but changed my mind.")
    sev, _ = determine_severity(p, CaseType.REFUND_REQUEST, False)
    assert sev == Severity.LOW


def test_refund_inconsistent_escalates_to_medium():
    p = parse_complaint("I want refund 500 taka.")
    sev, _ = determine_severity(p, CaseType.REFUND_REQUEST, evidence_verdict_is_contradictory=True)
    assert sev == Severity.MEDIUM


def test_other_vague_is_low():
    """SAMPLE-06: vague other → low."""
    p = parse_complaint("Something is wrong with my money. Please check.")
    sev, _ = determine_severity(p, CaseType.OTHER, False)
    assert sev == Severity.LOW


def test_merchant_settlement_is_medium():
    """SAMPLE-09: merchant_settlement_delay → medium."""
    p = parse_complaint("Yesterday's sales of 15000 taka not settled.")
    sev, _ = determine_severity(p, CaseType.MERCHANT_SETTLEMENT_DELAY, False)
    assert sev == Severity.MEDIUM


def test_agent_cash_in_pending_is_high():
    """SAMPLE-07: agent_cash_in_issue → high."""
    p = parse_complaint("আজ সকালে এজেন্টের কাছে ২০০০ টাকা ক্যাশ ইন করেছি, ব্যালেন্সে আসেনি")
    sev, _ = determine_severity(p, CaseType.AGENT_CASH_IN_ISSUE, False)
    assert sev == Severity.HIGH


def test_duplicate_payment_is_high():
    """SAMPLE-10: duplicate_payment → high."""
    p = parse_complaint("Paid electricity bill twice.")
    sev, _ = determine_severity(p, CaseType.DUPLICATE_PAYMENT, False)
    assert sev == Severity.HIGH


def test_large_amount_escalates_wrong_transfer_to_critical():
    p = parse_complaint("Sent to wrong number 150000 taka.")
    sev, _ = determine_severity(p, CaseType.WRONG_TRANSFER, False)
    assert sev == Severity.CRITICAL


# --------------------- Department mapping -------------------------------
def test_department_mapping_all_case_types():
    assert map_department(
        CaseType.WRONG_TRANSFER, Severity.HIGH, EvidenceVerdict.CONSISTENT
    ) == Department.DISPUTE_RESOLUTION

    assert map_department(
        CaseType.PAYMENT_FAILED, Severity.HIGH, EvidenceVerdict.CONSISTENT
    ) == Department.PAYMENTS_OPS

    assert map_department(
        CaseType.MERCHANT_SETTLEMENT_DELAY, Severity.MEDIUM, EvidenceVerdict.CONSISTENT
    ) == Department.MERCHANT_OPERATIONS

    assert map_department(
        CaseType.AGENT_CASH_IN_ISSUE, Severity.HIGH, EvidenceVerdict.CONSISTENT
    ) == Department.AGENT_OPERATIONS

    assert map_department(
        CaseType.PHISHING_OR_SOCIAL_ENGINEERING, Severity.CRITICAL, EvidenceVerdict.CONSISTENT
    ) == Department.FRAUD_RISK

    assert map_department(
        CaseType.DUPLICATE_PAYMENT, Severity.HIGH, EvidenceVerdict.CONSISTENT
    ) == Department.PAYMENTS_OPS

    assert map_department(
        CaseType.OTHER, Severity.LOW, EvidenceVerdict.INSUFFICIENT_DATA
    ) == Department.CUSTOMER_SUPPORT

    assert map_department(
        CaseType.REFUND_REQUEST, Severity.LOW, EvidenceVerdict.CONSISTENT
    ) == Department.CUSTOMER_SUPPORT