"""Matcher unit tests — calibrated for new transaction_status enum
(completed/failed/pending/reversed)."""
from app.schemas import TransactionStatus
from app.services.complaint_parser import parse_complaint
from app.services.matcher import find_relevant_transaction
from tests.fixtures import make_txn


def test_finds_exact_match_by_amount_and_recipient():
    c = parse_complaint("I sent 5000 taka to 01711223344 about 10 minutes ago.")
    txns = [make_txn("TX1", 5000, counterparty="01711223344", minutes_ago=5)]
    out = find_relevant_transaction(c, txns)
    assert out.best is not None
    assert out.best.transaction_id == "TX1"
    assert out.best.amount_match == "exact"
    assert out.best.recipient_match == "exact"


def test_returns_null_when_no_match():
    c = parse_complaint("I sent 5000 taka to 01711223344")
    txns = [make_txn("TX1", 999, counterparty="01999888777")]
    out = find_relevant_transaction(c, txns)
    assert out.best is None


def test_detects_duplicates():
    c = parse_complaint("Charged twice 500 taka")
    t1 = make_txn("TX1", 500, counterparty="01711000000", minutes_ago=10)
    t2 = make_txn("TX2", 500, counterparty="01711000000", minutes_ago=8)
    out = find_relevant_transaction(c, [t1, t2])
    assert any("TX1" in p and "TX2" in p for p in out.duplicates)


def test_chooses_highest_score_among_candidates():
    c = parse_complaint("I sent 1000 taka to 01711223344")
    txns = [
        make_txn("TX1", 1000, counterparty="01999000111", minutes_ago=120),
        make_txn("TX2", 1000, counterparty="01711223344", minutes_ago=20),
    ]
    out = find_relevant_transaction(c, txns)
    assert out.best is not None
    assert out.best.transaction_id == "TX2"


def test_empty_history_returns_null():
    c = parse_complaint("I sent 500 taka")
    out = find_relevant_transaction(c, [])
    assert out.best is None


def test_status_failed_marks_status_hint():
    c = parse_complaint("Payment failed 500 taka")
    t = make_txn("TX1", 500, status="failed", minutes_ago=10, type="payment")
    out = find_relevant_transaction(c, [t])
    assert out.best is not None
    assert out.best.status_hint is not None
    assert "failed_aligned" in out.best.status_hint


def test_status_completed_when_complaint_claims_failed():
    """SAMPLE-03 reversed: txn status 'failed' aligns with claim."""
    c = parse_complaint("Payment failed 500 taka")
    t = make_txn("TX1", 500, status="completed", minutes_ago=10, type="payment")
    out = find_relevant_transaction(c, [t])
    assert out.best is not None
    assert "contradicts" in (out.best.status_hint or "")


def test_detects_established_recipient_pattern():
    """SAMPLE-02: 3 prior transfers to same counterparty → established."""
    c = parse_complaint("I sent 2000 to the wrong person by mistake. Please reverse it.")
    txns = [
        make_txn("TXN-9202", 2000, counterparty="+8801812345678", minutes_ago=60),
        make_txn("TXN-9180", 2500, counterparty="+8801812345678", minutes_ago=24 * 60 * 4),
        make_txn("TXN-9145", 1500, counterparty="+8801812345678", minutes_ago=24 * 60 * 9),
    ]
    out = find_relevant_transaction(c, txns)
    # best is nullified by ambiguity/established pattern checks
    assert "established_recipient_pattern" in out.reasons


def test_detects_ambiguous_multiple_matches():
    """SAMPLE-08: 3 transactions of same amount, no recipient hint."""
    c = parse_complaint("I sent 1000 to my brother yesterday but he says he didn't get it.")
    txns = [
        make_txn("TXN-9801", 1000, counterparty="+8801712001122", minutes_ago=24 * 60),
        make_txn("TXN-9802", 1000, counterparty="+8801812334455", minutes_ago=24 * 60 - 60),
        make_txn("TXN-9803", 1000, counterparty="+8801712001122", minutes_ago=24 * 60 - 30,
                 status="failed"),
    ]
    out = find_relevant_transaction(c, txns)
    assert "ambiguous_match" in out.reasons
    assert "needs_clarification" in out.reasons