"""Case classifier unit tests."""
from app.schemas import CaseType
from app.services.case_classifier import classify_case
from app.services.complaint_parser import parse_complaint
from app.services.matcher import MatcherOutput


def _empty_matcher() -> MatcherOutput:
    return MatcherOutput(best=None, ranked=[], duplicates=[], reasons=[])


def test_classifies_wrong_transfer():
    p = parse_complaint("I sent to wrong number 5000 taka.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.WRONG_TRANSFER


def test_classifies_payment_failed():
    p = parse_complaint("Payment failed but money deducted 500 taka.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.PAYMENT_FAILED


def test_classifies_phishing_first():
    p = parse_complaint("OTP was shared with fake support agent.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.PHISHING_OR_SOCIAL_ENGINEERING


def test_classifies_duplicate():
    p = parse_complaint("Charged twice for the same order 500.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.DUPLICATE_PAYMENT


def test_classifies_refund():
    p = parse_complaint("I want a refund 1000 taka please.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.REFUND_REQUEST


def test_classifies_other_for_garbage():
    p = parse_complaint("hello there friend")
    assert classify_case(p, _empty_matcher())[0] == CaseType.OTHER


def test_phishing_beats_wrong_transfer():
    p = parse_complaint("I sent to wrong number, also they asked for OTP.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.PHISHING_OR_SOCIAL_ENGINEERING


def test_classifies_merchant_settlement():
    p = parse_complaint("My yesterday's sales of 15000 taka have not been settled.")
    assert classify_case(p, _empty_matcher())[0] == CaseType.MERCHANT_SETTLEMENT_DELAY


def test_classifies_agent_cash_in():
    p = parse_complaint("আমি আজ সকালে এজেন্টের কাছে ২০০০ টাকা ক্যাশ ইন করেছি কিন্তু ব্যালেন্সে আসেনি")
    assert classify_case(p, _empty_matcher())[0] == CaseType.AGENT_CASH_IN_ISSUE