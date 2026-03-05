from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger

from app.core.config import get_settings
from app.core.database import dispose_engine
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown hooks."""
    setup_logging()
    settings = get_settings()

    # VALIDATION PHASE
    from app.core.validation import validate_all, ConfigValidationError
    try:
        await validate_all()
    except ConfigValidationError as exc:
        logger.error("❌ Configuration validation failed: {}", exc)
        raise SystemExit(1)  # Hard exit with invalid config

    # STARTUP PHASE
    # Media directories are validated above, but ensure they exist
    for d in (settings.audio_dir, settings.video_dir, settings.output_dir, settings.ai_video_dir):
        d.mkdir(parents=True, exist_ok=True)

    logger.info("🚀 {} starting (env={})", settings.app_name, settings.app_env)
    yield

    # SHUTDOWN PHASE
    await dispose_engine()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # ── Security Headers Middleware ──────────────────────────
    # Add first so headers are always present
    from app.middleware.security_headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    # ── Authentication Middleware ─────────────────────────────
    from app.middleware.auth import AuthenticationMiddleware
    app.add_middleware(AuthenticationMiddleware)

    # ── CORS Middleware ───────────────────────────────────────
    # Parse allowed origins from settings (comma-separated list)
    allowed_origins = (
        ["*"] if settings.cors_allowed_origins == "*"
        else [origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()]
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # ── Error Handlers ────────────────────────────────────────
    from app.api.error_handlers import (
        http_exception_handler,
        validation_exception_handler,
        generic_exception_handler,
    )

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # ── Quick health check (no dependencies) ────────────────
    @app.get("/health", tags=["system"])
    async def health_check():
        return {"status": "healthy", "app": settings.app_name}

    # ── Prometheus Instrumentation ───────────────────────────
    from prometheus_fastapi_instrumentator import Instrumentator

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=False,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/health", "/metrics"],
        env_var_name="ENABLE_METRICS",
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )

    instrumentator.instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    logger.info("📊 Prometheus metrics exposed at /metrics")

    # ── Route registration ────────────────────────────────────
    from app.api.routes.pipeline import router as pipeline_router
    from app.api.routes.projects import router as projects_router
    from app.api.routes.system import router as system_router
    from app.api.routes.admin import router as admin_router

    app.include_router(pipeline_router)
    app.include_router(projects_router)
    app.include_router(system_router)
    app.include_router(admin_router)

    return app


app = create_app()
