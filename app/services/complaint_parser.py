"""Complaint parser — STEP 1 of the investigation pipeline.

Extracts structured signals from raw complaint text:
  - amount, currency
  - recipient hint (phone/account/merchant name)
  - time hint
  - merchant hint
  - intent keywords (per case_type)
  - fraud keywords
  - detected language
  - prompt-injection signals

Pure deterministic, regex + keyword sets. No LLM, no translation.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

from app.data.keywords import (
    AGENT_CASH_IN_ISSUE,
    DUPLICATE_PAYMENT,
    INJECTION_PATTERNS,
    MERCHANT_SETTLEMENT_DELAY,
    PAYMENT_FAILED,
    PHISHING,
    REFUND_REQUEST,
    RECIPIENT_HINTS_TRIGGERS,
    TIME_HINTS,
    URGENCY,
    WRONG_TRANSFER,
)
from app.schemas import ExtractedComplaintSignals, LanguageCode


# -----------------------------------------------------------------------------
# Regex helpers
# -----------------------------------------------------------------------------
# Bangla digits
_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# Amount patterns — English digits or Bangla digits, with optional currency,
# optional commas/spaces, decimal optional.
_AMOUNT_RE = re.compile(
    r"""
    (?P<amount>
        \d{1,3}(?:[,\s]\d{3})*        # 1,234 / 1 234 / 1234
        |
        \d+(?:\.\d{1,2})?              # 1234 / 1234.56
    )
    """,
    re.VERBOSE,
)

# Currency words / symbols (English + Bangla)
_CURRENCY_TOKENS = {
    "taka": "BDT",
    "টাকা": "BDT",
    "tk": "BDT",
    "bdt": "BDT",
    "৳": "BDT",
    "inr": "INR",
    "rupee": "INR",
    "rupees": "INR",
    "रुपये": "INR",
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
}

# Phone-number hint (Bangladesh + general): 11+ digits with possible separators
# We accept loose patterns: groups of 3-5 digits separated by space/hyphen.
_PHONE_RE = re.compile(
    r"\b(?:\+?88)?0?1[3-9](?:[\s-]?\d){8}\b"  # BD mobile
    r"|"
    r"\b\d{3}[\s-]\d{3}[\s-]\d{3,4}\b"        # generic grouped
    r"|"
    r"\b\d{10,15}\b"                          # raw long number
)

# Account hint: account / a/c / acct followed by digits
_ACCOUNT_RE = re.compile(
    r"(?i)\b(?:account|a/c|acct|acc(?:ount)?(?:\s*no\.?)?(?:\s*number)?)"
    r"\s*[:\-]?\s*([A-Z0-9\-]{4,20})"
)

# Transaction reference: txn / trx / transaction id
_TXN_REF_RE = re.compile(
    r"(?i)\b(?:txn|trx|trans(?:action)?(?:\s*id)?)\s*[:\-]?\s*([A-Z0-9\-]{4,20})"
)

# "to <phone/account/name>" — captures the recipient after "to"
_TO_RECIPIENT_RE = re.compile(
    r"(?i)\bto\s+(?:a\s+|the\s+|my\s+)?([a-z0-9][a-z0-9\s\-\.]{1,40}?)(?:[\.,;!?]|$)"
)


def _normalize_text(text: str) -> str:
    """Normalize unicode + lowercase + collapse whitespace."""
    if not text:
        return ""
    # NFKC normalizes some oddities
    text = unicodedata.normalize("NFKC", text)
    # Convert Bangla digits to ASCII
    text = text.translate(_BANGLA_DIGITS)
    text = text.lower()
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _detect_language(text: str) -> LanguageCode:
    """Detect Bangla vs English vs mixed (Banglish).

    Returns a LanguageCode value. Per the official sample contract, the
    only allowed values are en / bn / mixed.
    """
    if not text:
        return LanguageCode.EN
    has_bangla_script = any(
        "\u0980" <= ch <= "\u09FF" for ch in text
    )
    if has_bangla_script:
        return LanguageCode.BN
    # Heuristic for mixed (Banglish): romanized Bangla markers
    banglish_markers = [
        "amar", "taka", "kete", "niyechhe", "hoy", "nai", "ponno",
        "pathiyechi", "ferot", "bhai", "vai", "ekhon", "ekhono",
        "joma", "dokan", "bikreta", "dhukiyechi", "pochcheni",
        "shesh", "korte", "chai",
    ]
    norm = text.lower()
    hits = sum(1 for m in banglish_markers if re.search(rf"\b{re.escape(m)}\b", norm))
    if hits >= 2:
        return LanguageCode.MIXED
    return LanguageCode.EN


def _extract_amount(text_norm: str) -> Optional[float]:
    """Extract the most plausible monetary amount from text."""
    candidates: List[Tuple[float, int]] = []  # (value, priority)

    # Priority 1 — amount adjacent to currency token
    for token, _ in _CURRENCY_TOKENS.items():
        pattern = re.compile(
            rf"{re.escape(token)}\s*[:\-]?\s*(\d{{1,3}}(?:[,\s]\d{{3}})*|\d+(?:\.\d{{1,2}})?)",
            re.IGNORECASE,
        )
        m = pattern.search(text_norm)
        if m:
            num = m.group(1).replace(",", "").replace(" ", "")
            try:
                candidates.append((float(num), 100))
            except ValueError:
                pass

    # Priority 2 — number followed by currency
    for token, _ in _CURRENCY_TOKENS.items():
        pattern = re.compile(
            rf"(\d{{1,3}}(?:[,\s]\d{{3}})*|\d+(?:\.\d{{1,2}})?)\s*{re.escape(token)}",
            re.IGNORECASE,
        )
        m = pattern.search(text_norm)
        if m:
            num = m.group(1).replace(",", "").replace(" ", "")
            try:
                candidates.append((float(num), 90))
            except ValueError:
                pass

    # Priority 3 — explicit "amount of X" / "X taka" patterns
    # Note: the amount group must use a greedy \d+ first, with the
    # thousands-grouped pattern as a fallback, otherwise "sent 2000" gets
    # truncated to "sent 200".
    explicit_re = re.compile(
        r"(?:amount|charge|paid|sent|deducted|transferred|refund|price|total)"
        r"\s*(?:of\s+)?(?:rs\.?|tk\.?|bdt|inr|usd|\$)?\s*"
        r"(\d+(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)",
        re.IGNORECASE,
    )
    for m in explicit_re.finditer(text_norm):
        num = m.group(1).replace(",", "").replace(" ", "")
        try:
            candidates.append((float(num), 80))
        except ValueError:
            pass

    # Priority 4 — any other number; we then prefer the largest plausible
    # amount (>= 10) to avoid picking year-like small numbers.
    for m in _AMOUNT_RE.finditer(text_norm):
        raw = m.group("amount").replace(",", "").replace(" ", "")
        try:
            val = float(raw)
        except ValueError:
            continue
        # Skip numbers tied to "minutes/hours/days ago" — these are time, not money
        context_start = max(0, m.start() - 10)
        context_end = min(len(text_norm), m.end() + 20)
        ctx = text_norm[context_start:context_end]
        if re.search(r"\b(?:minutes?|hours?|seconds?|days?|weeks?|months?|years?)\s*(?:ago)?\b", ctx):
            continue
        if re.search(r"\bago\b", ctx):
            continue
        if val >= 1.0:
            candidates.append((val, 50))

    if not candidates:
        return None

    # Pick highest priority, then largest value
    candidates.sort(key=lambda c: (c[1], c[0]), reverse=True)
    return candidates[0][0]


def _extract_currency(text_norm: str) -> Optional[str]:
    """Detect currency token near the amount or anywhere in the text."""
    for token, code in _CURRENCY_TOKENS.items():
        if token in text_norm:
            return code
    return None


def _extract_recipient(text_orig: str, text_norm: str) -> Optional[str]:
    """Extract recipient hint (phone/account/merchant name)."""
    # Phone first
    m = _PHONE_RE.search(text_orig)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        # Skip pure-digit tokens that look like years (4-digit 19xx/20xx) when
        # nothing else is around. We do this conservatively: if it's exactly
        # 4 digits and there's no currency context, skip it.
        if len(digits) >= 10:
            return digits
        if 7 <= len(digits) <= 9:
            return digits

    m = _ACCOUNT_RE.search(text_orig)
    if m:
        return m.group(1)

    # "to <recipient>" pattern (last match preferred if multiple)
    _STOPWORDS_AFTER_TO = {
        "the", "a", "an", "my", "me", "you", "your", "it", "this", "that",
        "be", "do", "have", "has", "had", "can", "could", "will", "would",
        "should", "may", "might", "verify", "check", "confirm",
        "him", "her", "them", "us", "wrong", "right",
    }
    candidates: List[str] = []
    for m in _TO_RECIPIENT_RE.finditer(text_orig):
        cand = m.group(1).strip().rstrip(".,;!?")
        # Strip leading articles
        words = cand.split()
        while words and words[0].lower() in {"the", "a", "an", "my"}:
            words.pop(0)
        if not words:
            continue
        first_word = words[0]
        if first_word.lower() in _STOPWORDS_AFTER_TO:
            continue
        cleaned = " ".join(words)
        if len(cleaned) < 2:
            continue
        candidates.append(cleaned)
    if candidates:
        # Return longest reasonable candidate
        candidates.sort(key=len, reverse=True)
        return candidates[0][:50]

    return None


def _extract_time_hint(text_norm: str) -> Optional[str]:
    """Return the first matching time-hint phrase."""
    # Numeric hints like "5 minutes ago" — checked first so they take priority
    # over generic literal phrases like "minutes ago".
    m = re.search(r"\b(\d{1,3})\s*(seconds?|minutes?|hours?|days?|weeks?)\s*ago\b", text_norm)
    if m:
        return f"{m.group(1)} {m.group(2)} ago"
    m = re.search(r"\bago\s+(\d{1,3})\s*(seconds?|minutes?|hours?|days?|weeks?)\b", text_norm)
    if m:
        return f"{m.group(1)} {m.group(2)} ago"

    for hint in TIME_HINTS:
        if hint in text_norm:
            return hint
    return None


def _extract_merchant(text_norm: str) -> Optional[str]:
    """Heuristic merchant hint — usually a proper noun we can't be sure of."""
    # Look for a merchant-style word near "merchant/shop/online/order/store"
    merchant_triggers = [
        "merchant", "shop", "store", "seller", "vendor",
        "restaurant", "dokan", "bikreta", "online",
    ]
    for trig in merchant_triggers:
        pattern = re.compile(rf"\b{re.escape(trig)}\b\s*[:\-]?\s*([a-z0-9][a-z0-9\s\-]{{1,30}}?)(?:[\.,;!?]|$)")
        m = pattern.search(text_norm)
        if m:
            return m.group(1).strip()
    return None


def _match_any(text_norm: str, keywords: List[str]) -> List[str]:
    """Return list of keywords found in text."""
    hits: List[str] = []
    for kw in keywords:
        if not kw:
            continue
        if " " in kw or len(kw) > 4:
            # substring match
            if kw in text_norm:
                hits.append(kw)
        else:
            # word-boundary match for short tokens to avoid partial collisions
            if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text_norm):
                hits.append(kw)
    return hits


def _detect_injection(text_norm: str) -> tuple[bool, List[str]]:
    """Detect prompt-injection attempts in the complaint."""
    hits: List[str] = []
    for pat in INJECTION_PATTERNS:
        if pat in text_norm:
            hits.append(pat)
    # Also detect PII/secret requests
    secret_request_re = re.compile(
        r"\b(?:give|send|share|tell|provide|reveal)\s+(?:me\s+)?(?:your\s+|my\s+)?"
        r"(?:otp|pin|password|cvv|card\s*number|account\s*number|secret|code)\b",
        re.IGNORECASE,
    )
    for m in secret_request_re.finditer(text_norm):
        hits.append(f"secret_request:{m.group(0)}")
    return (len(hits) > 0, hits)


@dataclass
class ParsedComplaint:
    """Internal parsed structure used by other services."""

    raw: str
    normalized: str
    language: LanguageCode
    amount: Optional[float]
    currency: Optional[str]
    recipient_hint: Optional[str]
    time_hint: Optional[str]
    merchant_hint: Optional[str]

    intent_keywords: List[str] = field(default_factory=list)
    fraud_keywords: List[str] = field(default_factory=list)

    # Detected categories (presence flags)
    has_wrong_transfer: bool = False
    has_payment_failed: bool = False
    has_refund_request: bool = False
    has_duplicate_payment: bool = False
    has_merchant_settlement: bool = False
    has_agent_cash_in: bool = False
    has_phishing_signal: bool = False
    has_urgency: bool = False

    injection_detected: bool = False
    injection_signals: List[str] = field(default_factory=list)

    def to_signals(self) -> ExtractedComplaintSignals:
        """Convert to schema-bound output model."""
        return ExtractedComplaintSignals(
            amount=self.amount,
            currency=self.currency,
            recipient_hint=self.recipient_hint,
            time_hint=self.time_hint,
            merchant_hint=self.merchant_hint,
            intent_keywords=self.intent_keywords,
            fraud_keywords=self.fraud_keywords,
            language_detected=self.language,
            injection_detected=self.injection_detected,
            injection_signals=self.injection_signals,
        )


def parse_complaint(text: str) -> ParsedComplaint:
    """Parse raw complaint text into a structured ParsedComplaint."""
    raw = text or ""
    norm = _normalize_text(raw)

    language = _detect_language(raw)
    amount = _extract_amount(norm)
    currency = _extract_currency(norm)
    recipient = _extract_recipient(raw, norm)
    time_hint = _extract_time_hint(norm)
    merchant = _extract_merchant(norm)

    wrong = _match_any(norm, WRONG_TRANSFER)
    failed = _match_any(norm, PAYMENT_FAILED)
    refund = _match_any(norm, REFUND_REQUEST)
    duplicate = _match_any(norm, DUPLICATE_PAYMENT)
    merchant_sig = _match_any(norm, MERCHANT_SETTLEMENT_DELAY)
    agent_sig = _match_any(norm, AGENT_CASH_IN_ISSUE)
    phishing = _match_any(norm, PHISHING)
    urgent = _match_any(norm, URGENCY)

    intent_keywords: List[str] = []
    fraud_keywords: List[str] = []

    intent_keywords.extend(wrong)
    intent_keywords.extend(failed)
    intent_keywords.extend(refund)
    intent_keywords.extend(duplicate)
    intent_keywords.extend(merchant_sig)
    intent_keywords.extend(agent_sig)
    fraud_keywords.extend(phishing)
    fraud_keywords.extend(urgent)

    injection_detected, injection_signals = _detect_injection(norm)
    if phishing:
        fraud_keywords.extend(phishing)

    return ParsedComplaint(
        raw=raw,
        normalized=norm,
        language=language,
        amount=amount,
        currency=currency,
        recipient_hint=recipient,
        time_hint=time_hint,
        merchant_hint=merchant,
        intent_keywords=intent_keywords,
        fraud_keywords=fraud_keywords,
        has_wrong_transfer=bool(wrong),
        has_payment_failed=bool(failed),
        has_refund_request=bool(refund),
        has_duplicate_payment=bool(duplicate),
        has_merchant_settlement=bool(merchant_sig),
        has_agent_cash_in=bool(agent_sig),
        has_phishing_signal=bool(phishing),
        has_urgency=bool(urgent),
        injection_detected=injection_detected,
        injection_signals=injection_signals,
    )