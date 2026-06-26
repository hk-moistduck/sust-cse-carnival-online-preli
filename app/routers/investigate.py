"""HTTP router — primary investigation endpoint is /analyze-ticket.

Alias /investigate is also accepted for backward compatibility.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.logger import get_logger, log_event
from app.schemas import AnalyzeTicketRequest, AnalyzeTicketResponse
from app.services.investigator import investigate

router = APIRouter(tags=["investigate"])
logger = get_logger("app.routers.investigate")


@router.post(
    "/analyze-ticket",
    response_model=AnalyzeTicketResponse,
    summary="Analyze a customer support ticket against transaction history",
)
async def post_analyze_ticket(
    payload: AnalyzeTicketRequest, request: Request
) -> AnalyzeTicketResponse:
    """Run the investigation pipeline on a support ticket.

    The endpoint name is the official /analyze-ticket per the hackathon
    problem statement.
    """
    request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
    start = time.perf_counter()

    try:
        result = investigate(payload)
    except ValueError as e:
        log_event(
            logger,
            "ticket_validation_error",
            request_id=request_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:  # pragma: no cover — defensive
        log_event(
            logger,
            "ticket_unhandled_error",
            request_id=request_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Investigation failed",
        ) from e

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    log_event(
        logger,
        "request_complete",
        request_id=request_id,
        ticket_id=result.ticket_id,
        verdict=result.evidence_verdict.value,
        case_type=result.case_type.value,
        severity=result.severity.value,
        confidence=result.confidence,
        human_review=result.human_review_required,
        elapsed_ms=round(elapsed_ms, 2),
    )
    return result


# Backward-compatible alias
@router.post(
    "/investigate",
    response_model=AnalyzeTicketResponse,
    summary="Backward-compatible alias for /analyze-ticket",
    include_in_schema=False,
)
async def post_investigate_alias(
    payload: AnalyzeTicketRequest, request: Request
) -> AnalyzeTicketResponse:
    return await post_analyze_ticket(payload, request)