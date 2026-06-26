"""Investigator orchestrator — composes all services into one pipeline.

Aligned with the official SUST CSE Carnival 2026 sample case pack.
"""
from __future__ import annotations

import time
from typing import List

from app.logger import get_logger, log_event
from app.schemas import AnalyzeTicketRequest, AnalyzeTicketResponse
from app.services.case_classifier import classify_case
from app.services.complaint_parser import parse_complaint
from app.services.department import map_department
from app.services.evidence import evaluate_evidence
from app.services.matcher import find_relevant_transaction
from app.services.response_formatter import (
    build_agent_summary,
    build_next_action,
    build_response,
)
from app.services.safety import assess_safety
from app.services.severity import determine_severity


logger = get_logger("app.services.investigator")


def investigate(req: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Run the full investigation pipeline."""
    start = time.perf_counter()

    # STEP 1 — parse complaint
    parsed = parse_complaint(req.complaint)
    log_event(
        logger,
        "complaint_parsed",
        ticket_id=req.ticket_id,
        language=parsed.language.value,
        amount=parsed.amount,
        recipient=parsed.recipient_hint,
        intents=len(parsed.intent_keywords),
        fraud=len(parsed.fraud_keywords),
        injection=parsed.injection_detected,
    )

    # STEPS 2-4 — match transactions
    matcher_out = find_relevant_transaction(parsed, req.transaction_history)
    best = matcher_out.best
    ambiguity_detected = matcher_out.ambiguous_match
    established_count = matcher_out.established_recipient_count
    log_event(
        logger,
        "matcher_done",
        ticket_id=req.ticket_id,
        transactions=len(req.transaction_history),
        best_id=best.transaction_id if best else None,
        best_score=round(best.score, 3) if best else 0.0,
        duplicates=len(matcher_out.duplicates),
        ambiguous=ambiguity_detected,
        established_recipient=established_count,
    )

    # STEP 5 — evidence verdict
    evidence = evaluate_evidence(
        parsed=parsed,
        best=best,
        transactions_present=bool(req.transaction_history),
        ambiguity_detected=ambiguity_detected,
        established_recipient_count=established_count,
    )

    # Case classification
    case_type, case_reasons = classify_case(parsed, matcher_out)

    # Severity
    severity, severity_reasons = determine_severity(
        parsed=parsed,
        case_type=case_type,
        evidence_verdict_is_contradictory=(evidence.verdict.value == "inconsistent"),
        evidence_verdict_is_insufficient=(evidence.verdict.value == "insufficient_data"),
    )

    # Department
    department = map_department(case_type, severity, evidence.verdict)

    # Safety / human review
    safety = assess_safety(
        parsed=parsed,
        case_type=case_type,
        severity=severity,
        evidence_verdict=evidence.verdict,
        has_match=best is not None,
        ambiguity_detected=ambiguity_detected,
        established_recipient_count=established_count,
        user_type=req.user_type or "customer",
    )

    # Aggregate reason codes (de-dup, preserve order)
    all_reasons: List[str] = []
    for r in (
        matcher_out.reasons
        + evidence.reason_codes
        + case_reasons
        + severity_reasons
        + safety.reason_codes
    ):
        if r not in all_reasons:
            all_reasons.append(r)

    # Agent summary
    agent_summary = build_agent_summary(
        parsed=parsed,
        case_type=case_type,
        best=best,
        evidence_verdict=evidence.verdict,
        severity=severity,
        user_type=req.user_type or "customer",
    )

    # Recommended next action
    next_action = build_next_action(
        case_type=case_type,
        severity=severity,
        evidence_verdict=evidence.verdict,
        has_match=best is not None,
        ambiguity_detected=ambiguity_detected,
        user_type=req.user_type or "customer",
    )

    # Customer reply (in complaint's language)
    from app.services.reply_builder import build_customer_reply

    customer_reply = build_customer_reply(
        case_type=case_type,
        severity=severity,
        risk_flags=safety.risk_flags,
        language=(req.language or parsed.language.value or "en"),
        user_type=req.user_type or "customer",
        relevant_transaction_id=best.transaction_id if best else None,
        ambiguity_detected=ambiguity_detected,
        idx_seed=hash(req.complaint) & 0xFFFF,
    )

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    log_event(
        logger,
        "investigation_complete",
        ticket_id=req.ticket_id,
        case_type=case_type.value,
        severity=severity.value,
        verdict=evidence.verdict.value,
        confidence=round(evidence.confidence, 3),
        human_review=safety.requires_human_review,
        ms=round(elapsed_ms, 2),
    )

    return build_response(
        ticket_id=req.ticket_id,
        case_type=case_type,
        department=department,
        severity=severity,
        evidence_verdict=evidence.verdict,
        relevant_transaction_id=best.transaction_id if best else None,
        reason_codes=all_reasons,
        confidence=evidence.confidence,
        requires_human_review=safety.requires_human_review,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        risk_flags=safety.risk_flags,
        reasoning_ms=elapsed_ms,
        transactions_examined=len(req.transaction_history),
    )