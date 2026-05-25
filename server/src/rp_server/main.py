"""FastAPI application factory and configuration."""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from rp_server import __version__
from rp_server.config import settings
from rp_server.database import DbSession, engine
from rp_server.routers import admin, enroll, heartbeat, hosts, keys, metrics

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logging.basicConfig(
    format="%(message)s",
    level=getattr(logging, settings.log_level.upper()),
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    logger.info(
        "Remote-Pulse server starting",
        extra={"version": __version__, "log_level": settings.log_level},
    )
    yield
    logger.info("Remote-Pulse server shutting down")
    await engine.dispose()


app = FastAPI(
    title="Remote-Pulse Server",
    description="Fleet monitoring server for Remote-Pulse agents",
    version=__version__,
    lifespan=lifespan,
)


# Prometheus metrics middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record HTTP request duration for Prometheus metrics."""
    from rp_server.metrics_exporter import rp_http_request_duration_seconds

    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    rp_http_request_duration_seconds.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    ).observe(duration)

    return response


# Include routers
app.include_router(enroll.router)
app.include_router(heartbeat.router)
app.include_router(hosts.router)
app.include_router(metrics.router)
app.include_router(keys.router)
app.include_router(admin.router)


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        content={
            "status": "healthy",
            "version": __version__,
        }
    )


@app.get("/")
async def root() -> JSONResponse:
    """Root endpoint with server info."""
    return JSONResponse(
        content={
            "service": "remote-pulse-server",
            "version": __version__,
            "endpoints": {
                "health": "/health",
                "enroll": "/v1/enroll",
                "heartbeat": "/v1/heartbeat",
                "hosts": "/v1/hosts",
                "metrics": "/v1/metrics/{host_id}/sparkline",
                "prometheus_metrics": "/metrics",
            },
        }
    )


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(db: DbSession) -> Response:
    """Prometheus scrape endpoint. Computes fleet gauges on-demand.

    Public endpoint - no authentication required. Prometheus scrapes via LAN.
    Future F8 may add IP allowlist or token-based auth.
    """
    from rp_server.metrics_exporter import (
        get_content_type,
        get_metrics_output,
        refresh_fleet_gauges,
    )

    # Compute on-demand gauges from DB
    await refresh_fleet_gauges(db)

    # Return Prometheus text exposition format
    return Response(content=get_metrics_output(), media_type=get_content_type())
