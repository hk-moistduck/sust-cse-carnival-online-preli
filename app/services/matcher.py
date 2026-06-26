"""Transaction matcher — STEPS 2-4 of the investigation pipeline.

Reads every transaction, scores it against the parsed complaint using
amount / time / recipient / merchant / type / status signals, then
selects the best match (or None).

Pure deterministic. No LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.config import get_settings
from app.schemas import Transaction, TransactionStatus
from app.services import reason_codes as RC
from app.services.complaint_parser import ParsedComplaint


# Match score weights — tunable but deterministic
W_AMOUNT_EXACT = 0.45
W_AMOUNT_NEAR = 0.25
W_TIME_RECENT = 0.15
W_RECIPIENT_EXACT = 0.25
W_RECIPIENT_NEAR = 0.12
W_MERCHANT = 0.10
W_TYPE = 0.10
W_STATUS_HINT = 0.05


@dataclass
class MatchResult:
    """A single transaction scored against the complaint."""

    transaction_id: str
    score: float
    amount_match: str  # exact | near | none
    time_match: str  # exact | near | none
    recipient_match: str  # exact | near | none
    merchant_match: bool
    type_match: bool
    status_hint: Optional[str]
    triggered_reasons: List[str] = field(default_factory=list)


@dataclass
class MatcherOutput:
    """Top-level output of the matcher."""

    best: Optional[MatchResult]
    ranked: List[MatchResult]
    duplicates: List[Tuple[str, str]]  # pairs (txn_a, txn_b) suspected duplicate
    reasons: List[str] = field(default_factory=list)
    established_recipient_count: int = 0
    ambiguous_match: bool = False


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _norm_digits(s: Optional[str]) -> str:
    """Normalize phone/account: keep digits only, strip country code 880."""
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    # Bangladesh: strip country code 880 if present at the start
    if digits.startswith("880") and len(digits) > 10:
        digits = digits[3:]
    return digits


def _amount_similarity(a: Optional[float], b: Optional[float]) -> Tuple[float, str]:
    """Return (score 0..1, label) for two amounts."""
    if a is None or b is None:
        return (0.0, "none")
    if a == b:
        return (1.0, "exact")
    if b == 0:
        return (0.0, "none")
    diff_ratio = abs(a - b) / max(a, b)
    if diff_ratio <= 0.02:  # within 2%
        return (0.85, "near")
    if diff_ratio <= 0.10:  # within 10%
        return (0.5, "near")
    return (0.0, "none")


def _time_similarity(
    txn_ts: Optional[datetime],
    complaint_amount_signal: bool,
    time_hint: Optional[str] = None,
) -> Tuple[float, str]:
    """
    Score a transaction timestamp relative to "now".

    We do not have an absolute complaint timestamp — only a phrase like
    "yesterday" or "2 hours ago". We approximate recency by treating the
    complaint as describing a recent event.

    If the complaint explicitly contains a time_hint (e.g. "today",
    "yesterday", "2 hours ago"), we treat the transaction as plausibly
    recent regardless of its absolute date — because the customer
    description is what we have to go on.

    Returns:
      (1.0, "exact")  → within last hour OR explicit "today / minutes ago"
      (0.7, "near")   → within last 24h OR explicit "yesterday"
      (0.4, "near")   → within last 7 days
      (0.0, "none")   → no anchor or older than 7d
    """
    # If the complaint carries a recency hint, we treat the match as recent.
    if time_hint:
        th = time_hint.lower()
        strong_recent = any(
            x in th
            for x in [
                "today", "আজ", "aj", "ajke", "eimatro", "এইমাত্র",
                "minute", "second", "hour", "ঘণ্টা", "মিনিট",
            ]
        )
        yesterday = any(
            x in th
            for x in ["yesterday", "গতকাল", "kal", "gotokal"]
        )
        if strong_recent:
            return (1.0, "exact")
        if yesterday:
            return (0.85, "near")
        # Generic "ago" with a number
        if "ago" in th or "age" in th:
            return (0.7, "near")
        return (0.7, "near")  # any explicit time hint counts as near

    if txn_ts is None:
        return (0.0, "none")
    now = datetime.now(tz=timezone.utc)
    if txn_ts.tzinfo is None:
        txn_ts = txn_ts.replace(tzinfo=timezone.utc)
    delta = now - txn_ts
    seconds = delta.total_seconds()
    if seconds < 0:
        return (0.5, "near")
    if seconds <= 3600:
        return (1.0, "exact")
    if seconds <= 24 * 3600:
        return (0.7, "near")
    if seconds <= 7 * 24 * 3600:
        return (0.4, "near")
    return (0.0, "none")


def _recipient_similarity(
    txn_counterparty: Optional[str], hint: Optional[str]
) -> Tuple[float, str]:
    """Compare recipient hint with transaction counterparty."""
    if not txn_counterparty or not hint:
        return (0.0, "none")
    a = _norm_digits(hint)
    b = _norm_digits(txn_counterparty)
    if a and b:
        if a == b:
            return (1.0, "exact")
        # Suffix match — last 7-8 digits typical for BD numbers
        if len(a) >= 7 and len(b) >= 7 and a[-7:] == b[-7:]:
            return (0.8, "near")
    # String contains match
    th = hint.lower().strip()
    tc = txn_counterparty.lower().strip()
    if th and tc:
        if th in tc or tc in th:
            return (0.7, "near")
    return (0.0, "none")


def _merchant_similarity(merchant_hint: Optional[str], txn_counterparty: Optional[str]) -> bool:
    if not merchant_hint or not txn_counterparty:
        return False
    return merchant_hint.lower().strip() in txn_counterparty.lower()


def _type_matches(type_hint: Optional[str], txn_type: Optional[str]) -> bool:
    if not type_hint or not txn_type:
        return False
    from app.data.keywords import TYPE_KEYWORDS

    for canonical, words in TYPE_KEYWORDS.items():
        if canonical == type_hint:
            for w in words:
                if w.lower() in txn_type.lower():
                    return True
    return type_hint.lower() in txn_type.lower()


def _guess_type_hint(parsed: ParsedComplaint) -> Optional[str]:
    """Map complaint intent to a canonical type hint."""
    if parsed.has_wrong_transfer or parsed.has_duplicate_payment:
        return "transfer"
    if parsed.has_payment_failed or parsed.has_merchant_settlement:
        return "payment"
    if parsed.has_agent_cash_in:
        return "cash_in"
    if parsed.has_refund_request:
        return "refund"
    return None


def _status_hint(parsed: ParsedComplaint, txn_status: TransactionStatus) -> Optional[str]:
    """Annotate whether status aligns with complaint claim."""
    if parsed.has_payment_failed and txn_status == TransactionStatus.FAILED:
        return "status_failed_aligned_with_complaint"
    if parsed.has_payment_failed and txn_status == TransactionStatus.COMPLETED:
        return "status_completed_contradicts_payment_failed_claim"
    if parsed.has_refund_request and txn_status == TransactionStatus.REVERSED:
        return "status_reversed_aligned_with_refund_request"
    if parsed.has_refund_request and txn_status == TransactionStatus.COMPLETED:
        return "status_completed_no_refund_aligned"
    return None


def _detect_duplicates(
    transactions: List[Transaction], parsed: ParsedComplaint
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """
    Detect duplicate payments: same amount, same counterparty (digits),
    within a short time window.

    Returns (pairs, reason_codes).
    """
    pairs: List[Tuple[str, str]] = []
    reasons: List[str] = []

    if len(transactions) < 2:
        return pairs, reasons

    # Build a quick index
    indexed: List[Tuple[int, Transaction]] = []
    for i, t in enumerate(transactions):
        ts = t.parsed_timestamp()
        indexed.append((i, t, ts) if False else (i, (t, ts)))

    for i in range(len(transactions)):
        for j in range(i + 1, len(transactions)):
            ti = transactions[i]
            tj = transactions[j]
            if ti.transaction_id == tj.transaction_id:
                continue
            # Same amount (within 1 taka / 1 unit tolerance)
            if abs(ti.amount - tj.amount) > 1.0:
                continue
            # Same recipient (digits-based)
            ri = _norm_digits(ti.counterparty)
            rj = _norm_digits(tj.counterparty)
            if ri and rj and ri != rj:
                continue
            if (not ri) and (not rj) and (ti.counterparty or "").strip().lower() != (
                tj.counterparty or ""
            ).strip().lower():
                continue
            # Time window: within 5 minutes OR both within last 10 min
            tsi = ti.parsed_timestamp()
            tsj = tj.parsed_timestamp()
            close_time = False
            if tsi and tsj:
                delta = abs((tsi - tsj).total_seconds())
                if delta <= 300:  # 5 minutes
                    close_time = True
            elif tsi is None and tsj is None:
                close_time = True  # both undated — treat as candidate

            if close_time:
                pairs.append((ti.transaction_id, tj.transaction_id))
                reasons.append(RC.DUPLICATE_DETECTED)
    return pairs, reasons


def _detect_established_recipient(
    transactions: List[Transaction],
    best: Optional[MatchResult],
    parsed: ParsedComplaint,
) -> Tuple[int, List[str]]:
    """
    Detect 'established recipient pattern' (per SAMPLE-02): the same
    counterparty appears multiple times in transaction history BEFORE the
    relevant transaction, which contradicts a 'wrong transfer' claim.

    Returns (count_of_prior_transfers_to_same_counterparty, reason_codes).
    """
    reasons: List[str] = []
    if not best:
        return 0, reasons
    # Look up the best-matching transaction's counterparty
    best_txn = next(
        (t for t in transactions if t.transaction_id == best.transaction_id),
        None,
    )
    if not best_txn:
        return 0, reasons

    target_digits = _norm_digits(best_txn.counterparty)
    if not target_digits:
        return 0, reasons

    best_ts = best_txn.parsed_timestamp()
    prior_count = 0
    for t in transactions:
        if t.transaction_id == best_txn.transaction_id:
            continue
        d = _norm_digits(t.counterparty)
        if not d:
            continue
        if d[-7:] != target_digits[-7:]:  # compare by last-7-digits
            continue
        # Only count prior transactions (before the best txn time)
        ts = t.parsed_timestamp()
        if best_ts and ts and ts >= best_ts:
            continue
        prior_count += 1

    if prior_count >= 2:
        reasons.append("established_recipient_pattern")
    return prior_count, reasons


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def find_relevant_transaction(
    parsed: ParsedComplaint, transactions: List[Transaction]
) -> MatcherOutput:
    """Score every transaction, return best match and ranking."""
    reasons: List[str] = []
    if not transactions:
        reasons.append(RC.NO_MATCHING_TRANSACTION)
        return MatcherOutput(best=None, ranked=[], duplicates=[], reasons=reasons)

    type_hint = _guess_type_hint(parsed)
    candidates: List[MatchResult] = []

    for t in transactions:
        # If phishing/injection detected, still try to find a relevant txn
        # but we don't want to over-rely on numeric matches in fraud context.
        amount_score, amount_label = _amount_similarity(parsed.amount, t.amount)
        time_score, time_label = _time_similarity(
            t.parsed_timestamp(), parsed.amount is not None,
            time_hint=parsed.time_hint,
        )
        recip_score, recip_label = _recipient_similarity(
            t.counterparty, parsed.recipient_hint
        )
        merchant_hit = _merchant_similarity(parsed.merchant_hint, t.counterparty)
        type_hit = _type_matches(type_hint, t.type)
        status = _status_hint(parsed, t.normalized_status())

        score = 0.0
        if amount_label == "exact":
            score += W_AMOUNT_EXACT
        elif amount_label == "near":
            score += W_AMOUNT_NEAR

        if time_label == "exact":
            score += W_TIME_RECENT
        elif time_label == "near":
            score += W_TIME_RECENT * 0.6

        if recip_label == "exact":
            score += W_RECIPIENT_EXACT
        elif recip_label == "near":
            score += W_RECIPIENT_NEAR

        if merchant_hit:
            score += W_MERCHANT

        if type_hit:
            score += W_TYPE

        if status and "contradicts" in status:
            # Penalize contradictions
            score -= 0.20
        elif status and "aligned" in status:
            score += W_STATUS_HINT

        triggered: List[str] = []
        if amount_label == "exact":
            triggered.append(RC.AMOUNT_EXACT_MATCH)
        elif amount_label == "near":
            triggered.append(RC.AMOUNT_NEAR_MATCH)
        if time_label == "exact":
            triggered.append(RC.TIME_WINDOW_MATCH)
        elif time_label == "near":
            triggered.append(RC.TIME_WINDOW_NEAR)
        if recip_label == "exact":
            triggered.append(RC.RECIPIENT_EXACT_MATCH)
        elif recip_label == "near":
            triggered.append(RC.RECIPIENT_NEAR_MATCH)
        if merchant_hit:
            triggered.append(RC.MERCHANT_MATCH)
        if type_hit:
            triggered.append(RC.TYPE_MATCH)
        if status:
            triggered.append(status)

        candidates.append(
            MatchResult(
                transaction_id=t.transaction_id,
                score=score,
                amount_match=amount_label,
                time_match=time_label,
                recipient_match=recip_label,
                merchant_match=merchant_hit,
                type_match=type_hit,
                status_hint=status,
                triggered_reasons=triggered,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    duplicates, dup_reasons = _detect_duplicates(transactions, parsed)

    # If duplicates were detected, prefer the later-occurring transaction
    # (per SAMPLE-10: the suspected duplicate is the second one).
    if duplicates and candidates:
        # Find a candidate whose txn_id appears as the second element of any duplicate pair
        dup_seconds = {p[1] for p in duplicates}
        for c in candidates:
            if c.transaction_id in dup_seconds:
                # Promote to best
                candidates.remove(c)
                candidates.insert(0, c)
                break

    best: Optional[MatchResult] = None
    # Apply a minimum threshold so we don't pick a noise match
    threshold = 0.20
    if candidates and candidates[0].score >= threshold:
        best = candidates[0]
        reasons.extend(best.triggered_reasons)
    else:
        reasons.append(RC.NO_MATCHING_TRANSACTION)

    ambiguous = False
    # Ambiguity check (per SAMPLE-08): if multiple candidates have exact
    # amount match AND the complaint doesn't disambiguate them via recipient
    # hint or merchant hint, refuse to pick one.
    if (
        best is not None
        and len(candidates) >= 2
        and best.amount_match == "exact"
        and candidates[1].amount_match == "exact"
        and candidates[0].score - candidates[1].score < 0.05
        and not parsed.recipient_hint
        and not parsed.merchant_hint
    ):
        reasons.append("ambiguous_match")
        reasons.append("needs_clarification")
        ambiguous = True
        best = None

    reasons.extend(dup_reasons)

    # Established recipient detection (per SAMPLE-02)
    prior_count, prior_reasons = _detect_established_recipient(transactions, best, parsed)
    reasons.extend(prior_reasons)

    return MatcherOutput(
        best=best,
        ranked=candidates,
        duplicates=duplicates,
        reasons=reasons,
        established_recipient_count=prior_count,
        ambiguous_match=ambiguous,
    )