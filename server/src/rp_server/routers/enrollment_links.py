"""Enrollment magic-link generation router.

F7-6 implementation. Admin-only endpoint to generate enrollment tokens
with QR codes for easy agent onboarding.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

import jwt
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from rp_server.config import settings
from rp_server.database import DbSession
from rp_server.deps import current_user, require_admin
from rp_server.models import Enrollment, User
from rp_server.schemas import EnrollLinkRequest, EnrollLinkResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/enroll-link", tags=["enrollment"])

templates = Jinja2Templates(directory="src/rp_server/templates")


@router.get("/", response_class=HTMLResponse)
async def enroll_page(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    _admin: Annotated[User, Depends(require_admin)] = None,
):
    """Web UI to generate enrollment magic-link.

    Shows form: group, hostname, TTL, max_uses.
    Admin-only access.
    """
    return templates.TemplateResponse(
        "enroll_link.html",
        {
            "request": request,
            "user": user,
        },
    )


@router.post("/generate")
async def generate_enrollment_link(
    request_data: EnrollLinkRequest,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    _admin: Annotated[User, Depends(require_admin)] = None,
) -> EnrollLinkResponse:
    """Generate JWT enrollment token + magic URLs.

    Admin-only endpoint. Creates enrollment record and returns:
    - JWT token
    - Magic URLs for Unix/Windows install scripts
    - QR code SVG for mobile scanning

    Returns:
        EnrollLinkResponse with token, URLs, and QR code
    """
    # Generate JWT with embedded group + hostname hint
    jti = str(uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(hours=request_data.ttl_hours)

    payload = {
        "jti": jti,
        "iss": "remote-pulse-server",
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
        "group": request_data.group,
        "hostname": request_data.hostname,
        "max_uses": request_data.max_uses,
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    # Record enrollment in database
    enrollment = Enrollment(
        token_jti=jti,
        issued_by=user.email,
        group_name=request_data.group,
        expires_at=expires_at,
        max_uses=request_data.max_uses,
        used_count=0,
    )
    db.add(enrollment)
    await db.commit()

    # Generate magic URLs. Validate base_url against an allowlist to prevent
    # an attacker-controlled env (SERVER_URL=https://evil.example) from
    # turning admins into open-redirect launchers (review M10).
    base_url = settings.server_url.rstrip("/")
    allowed_install_hosts = {
        "rp.monxas.casa",
        "127.0.0.1",
        "localhost",
        # Tailnet MagicDNS name once F2 active
        "rp-server.monxas.ts.net",
    }
    try:
        from urllib.parse import urlparse

        parsed = urlparse(base_url)
        host = (parsed.hostname or "").lower()
    except Exception:
        host = ""

    if host and host not in allowed_install_hosts:
        logger.error(
            "Refusing to emit magic-link with unrecognised server_url",
            extra={"server_url": base_url, "host": host},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: server_url not in install allowlist",
        )

    magic_url_unix = f"{base_url}/install?token={token}"
    magic_url_windows = f"{base_url}/install.ps1?token={token}"

    # Generate QR code SVG
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(magic_url_unix)
    qr.make(fit=True)

    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathImage)

    # Convert PIL image to SVG string
    import io

    svg_io = io.BytesIO()
    img.save(svg_io)
    qr_code_svg = svg_io.getvalue().decode("utf-8")

    logger.info(
        "Enrollment link generated",
        extra={
            "issued_by": user.email,
            "group": request_data.group,
            "ttl_hours": request_data.ttl_hours,
            "max_uses": request_data.max_uses,
        },
    )

    return EnrollLinkResponse(
        token=token,
        expires_at=expires_at,
        magic_url_unix=magic_url_unix,
        magic_url_windows=magic_url_windows,
        qr_code_svg=qr_code_svg,
    )


@router.get("/{token_short}", response_class=HTMLResponse)
async def enroll_landing_page(
    token_short: str,
    request: Request,
):
    """Landing page when user scans QR or clicks magic-link.

    Shows OS detection + install command for that OS.
    Public endpoint - no auth required.
    """
    # TODO: Implement landing page with OS detection
    # For now, simple redirect to docs
    return templates.TemplateResponse(
        "enroll_landing.html",
        {
            "request": request,
            "token": token_short,
        },
    )
