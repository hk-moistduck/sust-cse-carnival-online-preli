"""Customer reply builder — official fintech tone, NEVER promises outcome.

Calibrated against the official sample case pack.

The reply language MUST match the input language:
  - English complaint → English reply
  - Bangla complaint  → Bangla reply
  - mixed            → English (default; safest for fintech ops)
  - merchant user    → business-formal English (or Bangla)

Every reply:
  - Acknowledges the concern empathetically
  - References the relevant transaction when known
  - Notes safety reminder for fraud / phishing cases
  - Asks for missing detail when ambiguous
  - NEVER requests PIN/OTP/password/card number
  - NEVER promises refund / reversal / fix
  - Uses safe language: 'any eligible amount will be returned through official channels'
"""
from __future__ import annotations

from typing import List

from app.data.keywords import BANNED_REPLY_PHRASES
from app.schemas import CaseType, Severity, UserType


# -----------------------------------------------------------------------------
# English phrase banks
# -----------------------------------------------------------------------------
_EN_OPENERS = [
    "Thank you for reaching out. We understand your concern.",
    "Thank you for contacting us. We have noted your concern.",
    "We have received your message and acknowledge the inconvenience this has caused.",
]

_EN_RECORD = [
    "We have noted your concern about transaction {txn}.",
    "Your case has been logged with reference to transaction {txn}.",
    "We have recorded the details regarding transaction {txn}.",
]

_EN_RECORD_NO_TXN = [
    "We have noted your concern and recorded the case.",
    "Your case has been logged in our system.",
    "We have recorded the details you shared.",
]

_EN_REVIEW = [
    "Our team will review the case and contact you through official support channels.",
    "The relevant team will carefully review the case.",
    "Our specialists will examine the matter and follow up with you.",
]

_EN_OUTCOME_SAFE = [
    "Any eligible amount will be returned through official channels if applicable.",
    "If applicable, any eligible adjustment will be processed through official procedures.",
    "Should the review confirm an issue, any applicable step will be carried out through the proper channel.",
]

_EN_FRAUD = [
    "Please do not share your PIN or OTP with anyone.",
    "We never ask for your PIN, OTP, or password. Please keep this information confidential.",
    "For your safety, never share your PIN, OTP, or password with anyone, even if they claim to be from us.",
]

_EN_PHISHING_REPLY = (
    "Thank you for reaching out before sharing any information. "
    "We never ask for your PIN, OTP, or password under any circumstances. "
    "Please do not share these with anyone, even if they claim to be from us. "
    "Our fraud team has been notified of this incident."
)

_EN_MERCHANT_OUTRO = (
    "Our merchant operations team will check the batch status and update you on the "
    "expected settlement time through official channels."
)

_EN_ASK_CLARIFY = [
    "To help you faster, please share the transaction ID, the amount involved, and a short description of what went wrong.",
    "Could you share more details, such as the transaction reference and approximate time?",
    "Please share the transaction ID, amount, and approximate time so we can investigate.",
]

_EN_DISPUTE_OPENING = [
    "Please do not share your PIN or OTP with anyone.",
    "We never ask for your PIN, OTP, or password under any circumstances.",
]

_EN_AGENT_OPS_OUTRO = (
    "Our agent operations team will verify the case and any eligible amount will be returned "
    "through official channels."
)

_EN_REFUND_OUTRO = (
    "Refunds for completed merchant payments depend on the merchant's own policy. "
    "We recommend contacting the merchant directly. If you need help reaching them, please reply "
    "and we will guide you."
)

_EN_DUPLICATE_OUTRO = (
    "Our payments team will verify with the biller and any eligible amount will be returned "
    "through official channels."
)

# -----------------------------------------------------------------------------
# Bangla phrase banks
# -----------------------------------------------------------------------------
_BN_OPENERS = [
    "আমরা আপনার অভিযোগ পেয়েছি এবং এটি গুরুত্ব সহকারে নিচ্ছি।",
    "আপনার বার্তা পেয়েছি। আমরা আপনার সমস্যাটি বুঝতে পেরেছি।",
]

_BN_RECORD = [
    "আপনার লেনদেন {txn} এর বিষয়ে আমরা অবগত হয়েছি।",
]

_BN_RECORD_NO_TXN = [
    "আপনার অভিযোগ আমরা রেকর্ড করেছি।",
]

_BN_REVIEW = [
    "আমাদের দল বিষয়টি পর্যালোচনা করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে।",
    "সংশ্লিষ্ট দল এটি যাচাই করবে এবং আপনার সাথে যোগাযোগ করবে।",
]

_BN_FRAUD = [
    "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।",
    "আমরা কখনো আপনার পিন, ওটিপি বা পাসওয়ার্ড চাই না।",
]

_BN_OUTCOME_SAFE = [
    "যদি প্রযোজ্য হয়, কোনো যোগ্য পরিমাণ অফিসিয়াল চ্যানেলে ফেরত দেওয়া হবে।",
]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _contains_banned(text: str) -> bool:
    low = text.lower()
    for phrase in BANNED_REPLY_PHRASES:
        if phrase in low:
            return True
    return False


def _assert_safe(text: str) -> str:
    out = text
    for phrase in BANNED_REPLY_PHRASES:
        idx = 0
        while True:
            low = out.lower()
            pos = low.find(phrase, idx)
            if pos == -1:
                break
            out = out[:pos] + "[redacted]" + out[pos + len(phrase):]
            idx = pos + len("[redacted]")
    return out


def _pick(bank: List[str], idx: int) -> str:
    return bank[idx % len(bank)]


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------
def build_customer_reply(
    case_type: CaseType,
    severity: Severity,
    risk_flags: List[str],
    language: str = "en",
    user_type: str = "customer",
    relevant_transaction_id: str | None = None,
    ambiguity_detected: bool = False,
    idx_seed: int = 0,
) -> str:
    """Compose a safe, professional customer reply in the complaint's language."""
    is_merchant = (user_type == "merchant")
    is_phishing = (case_type == CaseType.PHISHING_OR_SOCIAL_ENGINEERING)
    use_bangla = language == "bn"

    # Special case: phishing (always English per sample)
    if is_phishing:
        return _EN_PHISHING_REPLY

    # Special case: ambiguous — ask for clarification
    if ambiguity_detected:
        if use_bangla:
            return " ".join(
                [
                    _pick(_BN_OPENERS, idx_seed),
                    "একাধিক লেনদেন পাওয়া গেছে। সঠিক লেনদেন শনাক্ত করতে অনুগ্রহ করে প্রাপকের নম্বর বা লেনদেনের রেফারেন্স আইডি জানান।",
                    _pick(_BN_FRAUD, idx_seed + 1),
                ]
            )
        # English default
        if is_merchant:
            return (
                "Thank you for reaching out. We see multiple transactions matching your description. "
                "Could you share the transaction reference or recipient details so we can identify the right transaction? "
                "Please do not share your PIN or OTP with anyone."
            )
        return (
            f"Thank you for reaching out. {_pick(_EN_ASK_CLARIFY, idx_seed)} "
            f"Please do not share your PIN or OTP with anyone."
        )

    # Vague complaint (SAMPLE-06) — ask for clarification
    if case_type == CaseType.OTHER:
        if use_bangla:
            return " ".join(
                [
                    _pick(_BN_OPENERS, idx_seed),
                    _pick(_EN_ASK_CLARIFY, idx_seed).replace("Please", "অনুগ্রহ করে").replace("share", "জানান"),
                    _pick(_BN_FRAUD, idx_seed + 1),
                ]
            )
        return (
            f"{_pick(_EN_OPENERS, idx_seed)} {_pick(_EN_ASK_CLARIFY, idx_seed)} "
            f"Please do not share your PIN or OTP with anyone."
        )

    # Bangla replies for non-phishing cases
    if use_bangla:
        parts: List[str] = []
        parts.append(_pick(_BN_OPENERS, idx_seed))
        if relevant_transaction_id:
            parts.append(_pick(_BN_RECORD, idx_seed).format(txn=relevant_transaction_id))
        else:
            parts.append(_pick(_BN_RECORD_NO_TXN, idx_seed))
        parts.append(_pick(_BN_REVIEW, idx_seed + 1))
        if case_type in (
            CaseType.WRONG_TRANSFER,
            CaseType.PAYMENT_FAILED,
            CaseType.DUPLICATE_PAYMENT,
            CaseType.AGENT_CASH_IN_ISSUE,
        ):
            parts.append(_pick(_BN_OUTCOME_SAFE, idx_seed + 2))
        parts.append(_pick(_BN_FRAUD, idx_seed + 3))
        text = " ".join(parts)
    else:
        # English replies
        parts = []
        parts.append(_pick(_EN_OPENERS, idx_seed))
        if relevant_transaction_id:
            parts.append(_pick(_EN_RECORD, idx_seed).format(txn=relevant_transaction_id))
        else:
            parts.append(_pick(_EN_RECORD_NO_TXN, idx_seed))
        parts.append(_pick(_EN_REVIEW, idx_seed + 1))

        # Case-specific extra lines
        if case_type == CaseType.WRONG_TRANSFER:
            parts.append(_pick(_EN_DISPUTE_OPENING, idx_seed + 2))
        elif case_type == CaseType.PAYMENT_FAILED:
            parts.append(
                "Our payments team will review the case and any eligible amount will be returned "
                "through official channels."
            )
            parts.append(_pick(_EN_FRAUD, idx_seed + 3))
        elif case_type == CaseType.REFUND_REQUEST:
            parts.append(_EN_REFUND_OUTRO)
            parts.append(_pick(_EN_FRAUD, idx_seed + 3))
        elif case_type == CaseType.DUPLICATE_PAYMENT:
            parts.append(_EN_DUPLICATE_OUTRO)
            parts.append(_pick(_EN_FRAUD, idx_seed + 3))
        elif case_type == CaseType.MERCHANT_SETTLEMENT_DELAY:
            if is_merchant:
                parts.append(_EN_MERCHANT_OUTRO)
            else:
                parts.append(_EN_MERCHANT_OUTRO)
        elif case_type == CaseType.AGENT_CASH_IN_ISSUE:
            parts.append(_EN_AGENT_OPS_OUTRO)
            parts.append(_pick(_EN_FRAUD, idx_seed + 3))
        elif case_type in (
            CaseType.WRONG_TRANSFER,
            CaseType.PAYMENT_FAILED,
            CaseType.DUPLICATE_PAYMENT,
        ):
            parts.append(_pick(_EN_OUTCOME_SAFE, idx_seed + 2))
            parts.append(_pick(_EN_FRAUD, idx_seed + 3))

        text = " ".join(parts)

    # Defensive sanitization — should never trigger
    if _contains_banned(text):
        text = _assert_safe(text)

    return text.strip()