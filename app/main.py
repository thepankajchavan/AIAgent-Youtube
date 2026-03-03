from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import get_settings
from app.core.database import dispose_engine
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup / shutdown hooks."""
    setup_logging()
    settings = get_settings()

    # ensure media directories exist
    for d in (settings.audio_dir, settings.video_dir, settings.output_dir):
        d.mkdir(parents=True, exist_ok=True)

    logger.info("🚀  {} starting (env={})", settings.app_name, settings.app_env)
    yield
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Quick health check (no dependencies) ────────────────
    @app.get("/health", tags=["system"])
    async def health_check():
        return {"status": "healthy", "app": settings.app_name}

    # ── Route registration ────────────────────────────────────
    from app.api.routes.pipeline import router as pipeline_router
    from app.api.routes.projects import router as projects_router
    from app.api.routes.system import router as system_router

    app.include_router(pipeline_router)
    app.include_router(projects_router)
    app.include_router(system_router)

    return app


app = create_app()
