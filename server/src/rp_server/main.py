"""FastAPI application factory and configuration."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from rp_server import __version__
from rp_server.config import settings
from rp_server.database import DbSession, async_session_factory, engine
from rp_server.middleware.compat import APICompatMiddleware
from rp_server.audit_retention import retention_loop
from rp_server.routers import (
    admin,
    agent_commands,
    approvals,
    auth_oidc,
    commands,
    compat,
    dash_api,
    dash_audit,
    dash_commands,
    dash_enroll,
    dash_redirect,
    dash_retention,
    dash_settings,
    dash_stats,
    dash_webhooks,
    enroll,
    enrollment_links,
    heartbeat,
    hosts,
    keys,
    metrics,
)
from rp_server.webhooks import WebhookDispatcher, set_dispatcher
from starlette.middleware.sessions import SessionMiddleware

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
    # Wire up the outbound webhook dispatcher. It subscribes to the
    # in-process event bus and POSTs matching events to registered URLs.
    # Lives for the whole app lifetime so it shares one connection pool.
    dispatcher = WebhookDispatcher(async_session_factory)
    dispatcher.start()
    set_dispatcher(dispatcher)

    # Audit retention GC — fires every 24h to delete ``audit_events``
    # rows older than the policy in ``audit_retention_config``. See
    # ``rp_server.audit_retention`` for the rationale on rolling our
    # own asyncio task instead of pulling in APScheduler.
    import asyncio as _asyncio  # local import to avoid widening the module surface

    retention_task = _asyncio.create_task(
        retention_loop(async_session_factory),
        name="audit-retention-loop",
    )
    try:
        yield
    finally:
        logger.info("Remote-Pulse server shutting down")
        retention_task.cancel()
        try:
            await retention_task
        except (_asyncio.CancelledError, Exception):
            # Cancellation is the happy path; any other exception is
            # already logged by the loop itself. Either way we don't
            # want shutdown to block on it.
            pass
        await dispatcher.stop()
        set_dispatcher(None)
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

# Session middleware — signs cookies for the OIDC login flow (auth_oidc.py).
# Cookies are HttpOnly + SameSite=Lax + Secure (when running behind HTTPS).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="rp_session",
    same_site="lax",
    https_only=True,
    max_age=60 * 60 * 12,  # 12h
)


# Security headers middleware
@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # CSP: legacy /dash/ Jinja UI is gone (Phase 3 cutover) — every /dash/*
    # now 302s to /dash-next/*. The CDN allowances below remain only for the
    # ``/enroll-link/*`` HTML surfaces that still ship HTMX inline; they
    # will be tightened in a follow-up. The new /dash-next/ SPA is
    # 'self' only and uses self-hosted fonts (font-src 'self' data:).
    # connect-src 'self' covers fetch() + EventSource (SSE) to /v1/dash/stream.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
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
# Phase 2.5 — agent execution loop (pull commands + post results).
app.include_router(agent_commands.router)
app.include_router(auth_oidc.router)  # OIDC login flow (PocketID)
# ADR-0009 Phase 1+2: JSON API for the SvelteKit SPA. Mounted BEFORE the SPA
# static-files mount so /v1/dash/* is dispatched here, not by the catch-all.
app.include_router(dash_api.router)
app.include_router(dash_commands.router)  # Phase 2: Commands + Approvals
app.include_router(dash_audit.router)     # Phase 2: synthetic audit timeline
app.include_router(dash_settings.router)  # Phase 4: groups + users management
app.include_router(dash_retention.router)  # Audit retention policy (admin-only)
app.include_router(dash_webhooks.router)  # Outbound webhooks (admin-only)
app.include_router(dash_enroll.router)    # Phase 4+: admin magic-link issuance
app.include_router(dash_stats.router)     # ADR-0009 stats page: aggregated KPIs
# ADR-0009 Phase 3 cutover: the legacy Jinja+HTMX dashboard previously
# mounted via ``web.router`` is now replaced by a thin redirect shim that
# sends ``/dash/*`` to the SvelteKit SPA at ``/dash-next/*``. The one
# preserved endpoint (``/dash/host/{id}/sparkline-data``) lives inside
# this same router for backwards compat. The ``web`` module has been
# deleted (Phase 3 cleanup).
app.include_router(dash_redirect.router)
app.include_router(enrollment_links.router)  # F7-6: Magic-link enrollment


# ADR-0009 Phase 0: mount the SvelteKit SPA at /dash-next/ in parallel to the
# v1.0 Jinja dashboard at /dash/. The SPA itself enforces auth (it fetches
# /auth/me on boot and redirects to /auth/login on 401), so we mount the
# static files with no dependency-injected auth gate — `StaticFiles` is a
# raw ASGI app that bypasses FastAPI's dependency system anyway. Caddy's
# public matcher will be extended to cover /dash-next/* so the SPA shell
# loads without forward_auth headers (see docs/runbooks/rp-dash-next-caddy.md).
#
# The directory lives inside the installed package via
# `static/dash-next/<built assets>`. `scripts/build_dashboard.sh` populates
# it from `web/build/` after `npm run build`. The path is computed off
# `__file__` so it works both from a dev `uv run uvicorn …` checkout and
# from an installed wheel.
_DASH_NEXT_DIR = Path(__file__).parent / "static" / "dash-next"
if _DASH_NEXT_DIR.is_dir():
    # Starlette's StaticFiles(html=True) only serves index.html at the mount
    # root, not for nested paths. The SvelteKit client-side router needs
    # /dash-next/hosts/<id> (and any other deep link) to return the SPA
    # shell so it can boot and route. Subclass to fall back to index.html
    # on any 404 — this is the standard SPA-fallback pattern.
    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount(
        "/dash-next",
        SPAStaticFiles(directory=str(_DASH_NEXT_DIR), html=True),
        name="dash-next",
    )
else:
    logger.warning(
        "dash-next static directory not found; SPA mount skipped (%s)",
        _DASH_NEXT_DIR,
    )


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
