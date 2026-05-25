"""FastAPI application factory and configuration."""

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from rp_server import __version__
from rp_server.config import settings
from rp_server.database import DbSession, engine
from rp_server.middleware.compat import APICompatMiddleware
from rp_server.routers import (
    admin,
    approvals,
    commands,
    compat,
    enroll,
    enrollment_links,
    heartbeat,
    hosts,
    keys,
    metrics,
    web,
)

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


# CORS middleware — explicit allowlist (M11 review).
# Without this, FastAPI defaults to no CORS handling, which means browsers
# block cross-origin XHR. We allow only configured dashboard origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_dashboard_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# API Compatibility middleware
app.add_middleware(APICompatMiddleware)


# Security headers middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: allow self + inline scripts for HTMX, inline styles for uPlot
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


# Prometheus metrics middleware
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record HTTP request duration for Prometheus metrics.

    M8 fix: use route template path (e.g. ``/v1/hosts/{host_id}``) instead of
    raw path so we don't blow up Prometheus cardinality with UUIDs / variable
    segments.
    """
    from rp_server.metrics_exporter import rp_http_request_duration_seconds

    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Use route template if matched; fall back to "unmatched" for 404s so
    # unknown paths collapse into a single label instead of one per attacker URL.
    route = request.scope.get("route")
    path_label = getattr(route, "path", None) or "unmatched"

    rp_http_request_duration_seconds.labels(
        method=request.method,
        path=path_label,
        status=response.status_code,
    ).observe(duration)

    return response


# Include routers
app.include_router(compat.router)  # Public info endpoint first
app.include_router(enroll.router)
app.include_router(heartbeat.router)
app.include_router(hosts.router)
app.include_router(metrics.router)
app.include_router(keys.router)
app.include_router(admin.router)
app.include_router(commands.router)
app.include_router(approvals.router)
app.include_router(web.router)  # F5: Web dashboard
app.include_router(enrollment_links.router)  # F7-6: Magic-link enrollment


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
