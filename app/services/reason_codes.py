"""Canonical reason codes emitted by the investigator.

Every code is a stable, machine-readable string the judge can match.
"""
from __future__ import annotations

# Transaction / match reasons
AMOUNT_EXACT_MATCH = "amount_exact_match"
AMOUNT_NEAR_MATCH = "amount_near_match"
AMOUNT_NO_MATCH = "amount_no_match"
TIME_WINDOW_MATCH = "time_window_match"
TIME_WINDOW_NEAR = "time_window_near"
TIME_NO_ANCHOR = "time_no_anchor"
RECIPIENT_EXACT_MATCH = "recipient_exact_match"
RECIPIENT_NEAR_MATCH = "recipient_near_match"
RECIPIENT_NO_MATCH = "recipient_no_match"
MERCHANT_MATCH = "merchant_match"
TYPE_MATCH = "type_match"
NO_MATCHING_TRANSACTION = "no_matching_transaction"

# Evidence / contradiction
PAYMENT_DEBITED_BUT_FAILED = "payment_debited_but_status_failed"
PAYMENT_REPORTED_FAILED_BUT_SUCCESS = "payment_reported_failed_but_status_success"
DUPLICATE_DETECTED = "duplicate_amount_within_window"
WRONG_TRANSFER_DETECTED = "wrong_transfer_signal_detected"
REFUND_NOT_RECEIVED = "refund_not_received_signal"
MERCHANT_SETTLEMENT_DELAY_DETECTED = "merchant_settlement_delay_signal"
AGENT_CASH_IN_ISSUE_DETECTED = "agent_cash_in_issue_signal"

# Phishing / fraud / safety
PHISHING_DETECTED = "phishing_signal_detected"
PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
PII_REQUEST_DETECTED = "pii_request_detected"
SECRET_REQUEST_IN_COMPLAINT = "secret_request_in_complaint"
LARGE_AMOUNT_FLAG = "large_amount_flag"
CRITICAL_AMOUNT_FLAG = "critical_amount_flag"
REPEATED_SUSPICIOUS_ACTIVITY = "repeated_suspicious_activity_flag"

# Language / clarity
LANGUAGE_DETECTED = "language_detected"
BANGLA_DETECTED = "bangla_complaint_detected"
BANGLISH_DETECTED = "banglish_complaint_detected"
AMBIGUOUS_COMPLAINT = "ambiguous_complaint"
NO_CLEAR_INTENT = "no_clear_intent"

# Investigation meta
HUMAN_REVIEW_REQUIRED = "human_review_required"
DETERMINISTIC_REASONING = "deterministic_reasoning"
NO_TRANSACTION_HISTORY = "no_transaction_history_provided"


__all__ = [name for name in dir() if not name.startswith("_")]