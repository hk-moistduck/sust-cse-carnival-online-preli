"""FastAPI application entry point."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import __version__
from app.config import get_settings
from app.logger import configure_logging, get_logger, log_event
from app.routers.investigate import router as investigate_router
from app.schemas import HealthResponse


def create_app() -> FastAPI:
    """Application factory."""
    configure_logging()
    settings = get_settings()
    logger = get_logger("app.main")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered SupportOps Investigator. Reasons over transaction history "
            "to produce evidence-based investigation outputs. NOT a chatbot."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.include_router(investigate_router)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        """Friendly landing — send visitors to the API docs."""
        return RedirectResponse(url="/docs", status_code=307)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            app_name=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log_event(logger, "unhandled_error", path=str(request.url), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal investigation error", "error_type": exc.__class__.__name__},
        )

    log_event(
        logger,
        "app_started",
        version=settings.app_version,
        env=settings.environment,
    )
    return app


app = create_app()