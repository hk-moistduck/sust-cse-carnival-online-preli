"""Reusable test fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas import Transaction


def make_txn(
    txn_id: str,
    amount: float,
    counterparty: str = "01711000000",
    status: str = "success",
    minutes_ago: int = 30,
    type: str = "transfer",
    timestamp: str | None = None,
) -> Transaction:
    """Build a Transaction with sensible defaults."""
    if timestamp is None:
        ts = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes_ago)
        timestamp = ts.isoformat()
    return Transaction(
        transaction_id=txn_id,
        amount=amount,
        counterparty=counterparty,
        status=status,
        timestamp=timestamp,
        type=type,
    )