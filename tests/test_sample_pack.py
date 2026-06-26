"""Tests against the OFFICIAL sample case pack.

These tests directly mirror the 10 sample cases from the problem statement.
If a sample's expected_output disagrees with our output, the test captures
the disagreement but does not fail (since the spec says 'Other valid
responses may exist for the same input. Your output should be functionally
equivalent'). The test prints a diagnostic to help us refine.

For required enums and minimum contract fields, we DO assert exact match.
"""
from datetime import datetime, timezone

from app.schemas import (
    AnalyzeTicketRequest,
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    Transaction,
)
from app.services.investigator import investigate


def _txn(tid, amount, type_, status, counterparty, iso_ts):
    return Transaction(
        transaction_id=tid, amount=amount, counterparty=counterparty,
        status=status, timestamp=iso_ts, type=type_,
    )


# --------------------- SAMPLE-01 -------------------------------------
def test_sample_01_wrong_transfer_consistent():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-001",
        complaint="I sent 5000 taka to a wrong number around 2pm today. The number was supposed to be 01712345678 but I think I typed it wrong. The person isn't responding to my call. Please help me get my money back.",
        language="en", channel="in_app_chat", user_type="customer",
        campaign_context="boishakh_bonanza_day_1",
        transaction_history=[
            _txn("TXN-9101", 5000, "transfer", "completed",
                 "+8801719876543", "2026-04-14T14:08:22Z"),
            _txn("TXN-9087", 10000, "cash_in", "completed",
                 "AGENT-512", "2026-04-13T18:12:00Z"),
        ],
    )
    r = investigate(req)
    # Required-field exact match
    assert r.ticket_id == "TKT-001"
    assert r.case_type == CaseType.WRONG_TRANSFER
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.HIGH
    assert r.department == Department.DISPUTE_RESOLUTION
    assert r.relevant_transaction_id == "TXN-9101"
    assert r.human_review_required is True
    # Customer reply must NOT promise refund
    low = r.customer_reply.lower()
    assert "we have refunded" not in low
    assert "we will refund" not in low
    assert "we refunded" not in low


# --------------------- SAMPLE-02 -------------------------------------
def test_sample_02_wrong_transfer_inconsistent():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-002",
        complaint="I sent 2000 to the wrong person by mistake. Please reverse it.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-9202", 2000, "transfer", "completed",
                 "+8801812345678", "2026-04-14T11:30:00Z"),
            _txn("TXN-9180", 2500, "transfer", "completed",
                 "+8801812345678", "2026-04-10T09:15:00Z"),
            _txn("TXN-9145", 1500, "transfer", "completed",
                 "+8801812345678", "2026-04-05T17:45:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-002"
    assert r.case_type == CaseType.WRONG_TRANSFER
    assert r.evidence_verdict == EvidenceVerdict.INCONSISTENT
    assert r.severity == Severity.MEDIUM
    assert r.department == Department.DISPUTE_RESOLUTION
    assert r.relevant_transaction_id == "TXN-9202"
    assert r.human_review_required is True


# --------------------- SAMPLE-03 -------------------------------------
def test_sample_03_payment_failed_consistent():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-003",
        complaint="I tried to pay 1200 taka for my mobile recharge but the app showed failed. But my balance was deducted! Please refund my money.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-9301", 1200, "payment", "failed",
                 "MERCHANT-MOBILE-OP", "2026-04-14T16:00:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-003"
    assert r.case_type == CaseType.PAYMENT_FAILED
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.HIGH
    assert r.department == Department.PAYMENTS_OPS
    assert r.relevant_transaction_id == "TXN-9301"
    # SAMPLE-03 expects human_review_required=False
    assert r.human_review_required is False


# --------------------- SAMPLE-04 -------------------------------------
def test_sample_04_refund_request_low():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-004",
        complaint="I paid 500 to a merchant for a product but I changed my mind and don't want it anymore. Please refund my 500 taka.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-9401", 500, "payment", "completed",
                 "MERCHANT-7821", "2026-04-14T13:00:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-004"
    assert r.case_type == CaseType.REFUND_REQUEST
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.LOW
    assert r.department == Department.CUSTOMER_SUPPORT
    assert r.relevant_transaction_id == "TXN-9401"
    assert r.human_review_required is False
    low = r.customer_reply.lower()
    assert "we will refund" not in low
    assert "we refunded" not in low


# --------------------- SAMPLE-05 -------------------------------------
def test_sample_05_phishing():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-005",
        complaint="Someone called me saying they are from bKash and asked for my OTP. They said my account will be blocked if I don't share it. Is this real? I haven't shared anything yet.",
        language="en", channel="call_center", user_type="customer",
        transaction_history=[],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-005"
    assert r.case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING
    assert r.evidence_verdict == EvidenceVerdict.INSUFFICIENT_DATA
    assert r.severity == Severity.CRITICAL
    assert r.department == Department.FRAUD_RISK
    assert r.relevant_transaction_id is None
    assert r.human_review_required is True
    low = r.customer_reply.lower()
    assert "pin" in low or "otp" in low or "password" in low


# --------------------- SAMPLE-06 -------------------------------------
def test_sample_06_vague_complaint():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-006",
        complaint="Something is wrong with my money. Please check.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-9601", 3000, "cash_in", "completed",
                 "AGENT-220", "2026-04-13T10:00:00Z"),
            _txn("TXN-9602", 800, "transfer", "completed",
                 "+8801911223344", "2026-04-12T15:30:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-006"
    assert r.case_type == CaseType.OTHER
    assert r.evidence_verdict == EvidenceVerdict.INSUFFICIENT_DATA
    assert r.severity == Severity.LOW
    assert r.department == Department.CUSTOMER_SUPPORT
    assert r.relevant_transaction_id is None
    assert r.human_review_required is False


# --------------------- SAMPLE-07 -------------------------------------
def test_sample_07_agent_cash_in_bangla():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-007",
        complaint="আমি আজ সকালে এজেন্টের কাছে ২০০০ টাকা ক্যাশ ইন করেছি কিন্তু আমার ব্যালেন্সে টাকা আসেনি। এজেন্ট বলছে টাকা পাঠিয়েছে কিন্তু আমি দেখছি না।",
        language="bn", channel="call_center", user_type="customer",
        transaction_history=[
            _txn("TXN-9701", 2000, "cash_in", "pending",
                 "AGENT-318", "2026-04-14T09:30:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-007"
    assert r.case_type == CaseType.AGENT_CASH_IN_ISSUE
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.HIGH
    assert r.department == Department.AGENT_OPERATIONS
    assert r.relevant_transaction_id == "TXN-9701"
    assert r.human_review_required is True
    # Customer reply should be in Bangla
    assert any("\u0980" <= ch <= "\u09FF" for ch in r.customer_reply)


# --------------------- SAMPLE-08 -------------------------------------
def test_sample_08_ambiguous_match():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-008",
        complaint="I sent 1000 to my brother yesterday but he says he didn't get it. Please check.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-9801", 1000, "transfer", "completed",
                 "+8801712001122", "2026-04-13T11:20:00Z"),
            _txn("TXN-9802", 1000, "transfer", "completed",
                 "+8801812334455", "2026-04-13T19:45:00Z"),
            _txn("TXN-9803", 1000, "transfer", "failed",
                 "+8801712001122", "2026-04-13T20:10:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-008"
    assert r.case_type == CaseType.WRONG_TRANSFER
    assert r.evidence_verdict == EvidenceVerdict.INSUFFICIENT_DATA
    assert r.severity == Severity.MEDIUM
    assert r.department == Department.DISPUTE_RESOLUTION
    assert r.relevant_transaction_id is None
    assert r.human_review_required is False


# --------------------- SAMPLE-09 -------------------------------------
def test_sample_09_merchant_settlement_delay():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-009",
        complaint="I am a merchant. My yesterday's sales of 15000 taka have not been settled to my account. Settlement usually happens by 11am next day. Please check.",
        language="en", channel="merchant_portal", user_type="merchant",
        transaction_history=[
            _txn("TXN-9901", 15000, "settlement", "pending",
                 "MERCHANT-SELF", "2026-04-13T18:00:00Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-009"
    assert r.case_type == CaseType.MERCHANT_SETTLEMENT_DELAY
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.MEDIUM
    assert r.department == Department.MERCHANT_OPERATIONS
    assert r.relevant_transaction_id == "TXN-9901"
    assert r.human_review_required is False


# --------------------- SAMPLE-10 -------------------------------------
def test_sample_10_duplicate_payment():
    req = AnalyzeTicketRequest(
        ticket_id="TKT-010",
        complaint="I paid my electricity bill 850 taka but it deducted twice from my account. Please check, I only paid once.",
        language="en", channel="in_app_chat", user_type="customer",
        transaction_history=[
            _txn("TXN-10001", 850, "payment", "completed",
                 "BILLER-DESCO", "2026-04-14T08:15:30Z"),
            _txn("TXN-10002", 850, "payment", "completed",
                 "BILLER-DESCO", "2026-04-14T08:15:42Z"),
        ],
    )
    r = investigate(req)
    assert r.ticket_id == "TKT-010"
    assert r.case_type == CaseType.DUPLICATE_PAYMENT
    assert r.evidence_verdict == EvidenceVerdict.CONSISTENT
    assert r.severity == Severity.HIGH
    assert r.department == Department.PAYMENTS_OPS
    # SAMPLE-10 expects the SECOND transaction (suspected duplicate)
    assert r.relevant_transaction_id == "TXN-10002"
    assert r.human_review_required is True
    low = r.customer_reply.lower()
    assert "we will refund" not in low
    assert "we refunded" not in low


# --------------------- Bonus: end-to-end performance ---------------------
def test_response_time_under_2s():
    import time
    req = AnalyzeTicketRequest(
        ticket_id="TKT-PERF",
        complaint="I sent 5000 taka to 01711223344 wrong number",
        transaction_history=[
            _txn("TX1", 5000, "transfer", "completed",
                 "+8801712345678", datetime.now(timezone.utc).isoformat()),
        ],
    )
    start = time.perf_counter()
    r = investigate(req)
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0
    assert r.investigation_metadata["reasoning_ms"] < 2000