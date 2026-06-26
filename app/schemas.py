"""Pydantic request/response schemas — aligned with the official
SUST CSE Carnival 2026 sample case pack contract.

Endpoint: POST /analyze-ticket
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# -----------------------------------------------------------------------------
# Enums (strict — match official sample contract exactly)
# -----------------------------------------------------------------------------
class LanguageCode(str, Enum):
    EN = "en"
    BN = "bn"
    MIXED = "mixed"


class Channel(str, Enum):
    IN_APP_CHAT = "in_app_chat"
    CALL_CENTER = "call_center"
    EMAIL = "email"
    MERCHANT_PORTAL = "merchant_portal"
    FIELD_AGENT = "field_agent"


class UserType(str, Enum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    AGENT = "agent"
    UNKNOWN = "unknown"


class CaseType(str, Enum):
    WRONG_TRANSFER = "wrong_transfer"
    PAYMENT_FAILED = "payment_failed"
    REFUND_REQUEST = "refund_request"
    DUPLICATE_PAYMENT = "duplicate_payment"
    MERCHANT_SETTLEMENT_DELAY = "merchant_settlement_delay"
    AGENT_CASH_IN_ISSUE = "agent_cash_in_issue"
    PHISHING_OR_SOCIAL_ENGINEERING = "phishing_or_social_engineering"
    OTHER = "other"


class Department(str, Enum):
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENTS_OPS = "payments_ops"
    MERCHANT_OPERATIONS = "merchant_operations"
    AGENT_OPERATIONS = "agent_operations"
    FRAUD_RISK = "fraud_risk"
    CUSTOMER_SUPPORT = "customer_support"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceVerdict(str, Enum):
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"
    INSUFFICIENT_DATA = "insufficient_data"


class TransactionType(str, Enum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    SETTLEMENT = "settlement"
    REFUND = "refund"


class TransactionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING = "pending"
    REVERSED = "reversed"


# -----------------------------------------------------------------------------
# Request models
# -----------------------------------------------------------------------------
class Transaction(BaseModel):
    """A single transaction record from the customer's history."""

    model_config = ConfigDict(extra="allow")

    transaction_id: str = Field(..., min_length=1, description="Unique transaction identifier")
    amount: float = Field(..., ge=0, description="Transaction amount (currency-agnostic)")
    timestamp: Optional[str] = Field(
        None, description="ISO-8601 timestamp; may be None for legacy records"
    )
    status: Optional[str] = Field(
        None, description="completed | failed | pending | reversed"
    )
    counterparty: Optional[str] = Field(
        None, description="Recipient name, phone number, account, or merchant"
    )
    type: Optional[str] = Field(
        None, description="transfer | payment | cash_in | cash_out | settlement | refund"
    )

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return v.strip().lower()
        return v

    def parsed_timestamp(self):
        """Parse timestamp safely; return None if unparseable."""
        if not self.timestamp:
            return None
        try:
            ts = self.timestamp.replace("Z", "+00:00")
            from datetime import datetime
            return datetime.fromisoformat(ts)
        except (ValueError, AttributeError):
            return None

    def normalized_status(self) -> TransactionStatus:
        """Return enum-safe status, accepting legacy aliases."""
        s = (self.status or "").strip().lower()
        mapping = {
            "completed": TransactionStatus.COMPLETED,
            "complete": TransactionStatus.COMPLETED,
            "success": TransactionStatus.COMPLETED,
            "successful": TransactionStatus.COMPLETED,
            "failed": TransactionStatus.FAILED,
            "failure": TransactionStatus.FAILED,
            "declined": TransactionStatus.FAILED,
            "pending": TransactionStatus.PENDING,
            "processing": TransactionStatus.PENDING,
            "reversed": TransactionStatus.REVERSED,
            "refunded": TransactionStatus.REVERSED,
        }
        return mapping.get(s, TransactionStatus.FAILED)

    def normalized_type(self) -> Optional[TransactionType]:
        """Return enum-safe transaction type, accepting legacy aliases."""
        if not self.type:
            return None
        t = self.type.strip().lower()
        mapping = {
            "transfer": TransactionType.TRANSFER,
            "transfers": TransactionType.TRANSFER,
            "payment": TransactionType.PAYMENT,
            "payments": TransactionType.PAYMENT,
            "cash_in": TransactionType.CASH_IN,
            "cash-in": TransactionType.CASH_IN,
            "cashin": TransactionType.CASH_IN,
            "deposit": TransactionType.CASH_IN,
            "cash_out": TransactionType.CASH_OUT,
            "cash-out": TransactionType.CASH_OUT,
            "cashout": TransactionType.CASH_OUT,
            "withdraw": TransactionType.CASH_OUT,
            "withdrawal": TransactionType.CASH_OUT,
            "atm": TransactionType.CASH_OUT,
            "settlement": TransactionType.SETTLEMENT,
            "settle": TransactionType.SETTLEMENT,
            "refund": TransactionType.REFUND,
            "reversal": TransactionType.REFUND,
        }
        return mapping.get(t)


class AnalyzeTicketRequest(BaseModel):
    """Incoming investigation request — exact field names per official sample."""

    model_config = ConfigDict(extra="allow")

    ticket_id: str = Field(..., min_length=1, description="Unique ticket identifier")
    complaint: str = Field(..., min_length=1, description="Customer complaint text")
    language: Optional[str] = Field(None, description="en | bn | mixed")
    channel: Optional[str] = Field(
        None, description="in_app_chat | call_center | email | merchant_portal | field_agent"
    )
    user_type: Optional[str] = Field(
        None, description="customer | merchant | agent | unknown"
    )
    campaign_context: Optional[str] = Field(None, description="Marketing campaign tag")
    transaction_history: List[Transaction] = Field(
        default_factory=list, description="List of transactions to investigate"
    )
    metadata: Optional[dict] = Field(None, description="Free-form metadata")


# -----------------------------------------------------------------------------
# Response sub-models
# -----------------------------------------------------------------------------
class ExtractedComplaintSignals(BaseModel):
    """Internal: structured signals extracted from the raw complaint."""

    amount: Optional[float] = None
    currency: Optional[str] = None
    recipient_hint: Optional[str] = None
    time_hint: Optional[str] = None
    merchant_hint: Optional[str] = None
    intent_keywords: List[str] = Field(default_factory=list)
    fraud_keywords: List[str] = Field(default_factory=list)
    language_detected: LanguageCode = LanguageCode.EN
    injection_detected: bool = False
    injection_signals: List[str] = Field(default_factory=list)


class AnalyzeTicketResponse(BaseModel):
    """Full investigation output — exact field names per official sample."""

    # Required
    ticket_id: str
    relevant_transaction_id: Optional[str] = None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    # Optional but valuable
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    reason_codes: List[str] = Field(default_factory=list)
    # Internal extensions (allowed by extra="allow" pattern but kept separate)
    risk_flags: List[str] = Field(default_factory=list)
    investigation_metadata: Optional[dict] = None


class HealthResponse(BaseModel):
    """Liveness probe."""

    status: str = "ok"
    app_name: str
    version: str
    environment: str