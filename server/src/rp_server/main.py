"""FastAPI application factory and configuration."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from rp_server import __version__
from rp_server.config import settings
from rp_server.database import engine
from rp_server.routers import enroll, heartbeat, hosts

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

# Include routers
app.include_router(enroll.router)
app.include_router(heartbeat.router)
app.include_router(hosts.router)


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
            },
        }
    )
