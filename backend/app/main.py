"""
FaST Navigator Backend - FastAPI Application

Main entry point for the backend service.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings, require_postgres_url
from app.db.migrate import apply_migrations
from app.db.pool import create_pool
from app.logging_setup import configure_logging
from app.api import router as api_router
from app.api.internal import router as internal_router
from app.api.plans import router as plans_router
from app.calc.assemble import ParcelNotFound
from app.plans.service import Conflict, Invalid, NotFound
from app.plans.states import TransitionError
from app.sources.errors import SourceUnavailable

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the database (POSTGRES_URL is mandatory) and migrate before serving."""
    settings = get_settings()
    logger.info("%s v%s starting — prefix=%s debug=%s",
                settings.app_name, settings.app_version,
                settings.api_prefix, settings.debug)
    app.state.pool = await create_pool(require_postgres_url())
    try:
        async with app.state.pool.acquire() as conn:
            await apply_migrations(conn)
        yield
    finally:
        await app.state.pool.close()
        logger.info("%s shutting down", settings.app_name)


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()
    configure_logging(settings.log_level)
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="FaST Navigator - Backend API for Nekazari Platform",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )
    
    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Health check (at root for k8s probes)
    @app.get("/health")
    async def health_check():
        """Health check endpoint for Kubernetes probes."""
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
        }
    
    @app.exception_handler(SourceUnavailable)
    async def source_unavailable(request, exc: SourceUnavailable):
        """Spec §12: a failing source stops the calculation and is named; nothing is inferred."""
        return JSONResponse(status_code=503, content={"error": "source_unavailable",
                                                      "source": exc.source, "detail": exc.detail})

    @app.exception_handler(NotFound)
    async def not_found(request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": "not_found", "detail": str(exc)})

    @app.exception_handler(ParcelNotFound)
    async def parcel_not_found(request, exc: ParcelNotFound):
        return JSONResponse(status_code=404, content={"error": "parcel_not_found",
                                                      "detail": exc.urn})

    @app.exception_handler(Conflict)
    async def conflict(request, exc: Conflict):
        return JSONResponse(status_code=409, content={"error": "conflict", "detail": str(exc)})

    @app.exception_handler(TransitionError)
    async def transition_error(request, exc: TransitionError):
        status = 403 if exc.code == "forbidden" else 409
        return JSONResponse(status_code=status, content={"error": exc.code, "detail": exc.detail})

    @app.exception_handler(Invalid)
    async def invalid(request, exc: Invalid):
        return JSONResponse(status_code=422, content={"error": "invalid", "detail": str(exc)})

    # Include API routes
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(plans_router, prefix=settings.api_prefix)

    # Internal routes (entity-manager, other in-cluster callers) — authenticated
    # by X-Internal-Service-Secret, NOT gateway headers. See app/api/internal.py.
    app.include_router(internal_router, prefix=settings.api_prefix)

    return app


# Create application instance
app = create_app()
