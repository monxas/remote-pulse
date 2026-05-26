"""Dashboard magic-link enrollment endpoints (ADR-0009 follow-up).

Exposes a small admin-only API so operators can issue, list and revoke
enrollment magic-links straight from the SvelteKit dashboard, instead of
having to drop to the CLI or the Telegram bot.

Endpoints
---------
- ``POST   /v1/dash/enroll/links``         — create a new magic-link
- ``GET    /v1/dash/enroll/links``         — list active (non-expired,
  non-exhausted) links
- ``DELETE /v1/dash/enroll/links/{jti}``   — soft-revoke a link

The token itself is minted with :func:`rp_server.auth.create_enrollment_token`
(the canonical helper already used by the CLI / Telegram bot path), so any
future change to claim shape is picked up automatically.

The existing :mod:`rp_server.routers.enrollment_links` router is intentionally
left untouched — it still serves the legacy Jinja UI and the public landing
page at ``/enroll-link/{token_short}``.

Soft-revoke
-----------
``Enrollment`` has no ``revoked`` column. To preserve the audit trail of who
issued what, we revoke a link by setting ``expires_at = now()`` and bumping
``used_count`` to ``max_uses``. The agent-side validator (see
``routers/enroll.py``) rejects both conditions, so the link becomes inert
without a destructive ``DELETE``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from rp_server.auth import create_enrollment_token
from rp_server.config import settings
from rp_server.database import DbSession
from rp_server.deps import current_user, require_admin
from rp_server.models import Enrollment, User
from rp_server.permissions import user_has_permission

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash/enroll", tags=["dash-enroll"])


# --------------------------------------------------------------------------- #
# Allowlist (mirror of enrollment_links.py)
# --------------------------------------------------------------------------- #

# We refuse to embed an attacker-controlled host in the magic URL. Keep this
# in sync with ``routers/enrollment_links.py``; both routers exist while the
# old Jinja UI is still in place.
_ALLOWED_INSTALL_HOSTS: frozenset[str] = frozenset(
    {
        "rp.monxas.casa",
        "127.0.0.1",
        "localhost",
        "rp-server.monxas.ts.net",
    }
)


def _safe_base_url() -> str:
    base_url = settings.server_url.rstrip("/")
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except Exception:
        host = ""
    if host and host not in _ALLOWED_INSTALL_HOSTS:
        logger.error(
            "Refusing to emit magic-link with unrecognised server_url",
            extra={"server_url": base_url, "host": host},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: server_url not in install allowlist",
        )
    return base_url


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class EnrollLinkCreate(BaseModel):
    """Request body for ``POST /v1/dash/enroll/links``.

    ``group_name`` mirrors the column name in ``enrollments`` so the JSON
    matches the listing schema below. ``label`` is metadata that lands in the
    structured log only; it does not get persisted (the ``Enrollment`` table
    has no free-form description column today).
    """

    group_name: str = Field(default="default", min_length=1, max_length=63)
    ttl_hours: int = Field(default=24, ge=1, le=720)  # 1 hour .. 30 days
    max_uses: int = Field(default=1, ge=1, le=100)
    label: str | None = Field(default=None, max_length=120)

    @field_validator("group_name")
    @classmethod
    def _check_group(cls, v: str) -> str:
        # Match the regex from dash_settings._validate_group_name; we duplicate
        # the check rather than importing to avoid coupling the two modules.
        import re

        if not re.fullmatch(r"^[a-zA-Z0-9][a-zA-Z0-9_\-.]{0,62}$", v):
            raise ValueError(
                "Invalid group name. Must start with alphanumeric, "
                "1-63 chars, only [a-zA-Z0-9_.-]."
            )
        return v


class EnrollLinkOut(BaseModel):
    """Response body when creating a magic-link.

    Includes the full install URL so the UI can copy/render a QR right away.
    The raw JWT is *also* returned for power users / CLI parity.
    """

    model_config = ConfigDict(from_attributes=True)

    url: str
    install_url_windows: str
    token: str
    token_jti: str
    group_name: str
    issued_by: str
    expires_at: datetime
    expires_in_hours: int
    max_uses: int
    used_count: int = 0
    label: str | None = None


class EnrollLinkSummary(BaseModel):
    """Row in the active-links listing.

    Does NOT include the raw JWT — only the jti is exposed so the UI can
    revoke / display. The token itself is one-shot information that we hand
    out exactly once at creation time.
    """

    model_config = ConfigDict(from_attributes=True)

    token_jti: str
    group_name: str
    issued_by: str
    expires_at: datetime
    max_uses: int
    used_count: int
    created_at: datetime


class EnrollLinkListResponse(BaseModel):
    links: list[EnrollLinkSummary]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.post(
    "/links",
    response_model=EnrollLinkOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_enroll_link(
    payload: EnrollLinkCreate,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> EnrollLinkOut:
    """Issue a new enrollment magic-link.

    Row-level ACL: admins bypass, everyone else needs the ``enroll.create``
    permission scoped to ``payload.group_name`` (or ``*``). Reuses
    :func:`rp_server.auth.create_enrollment_token` so the JWT shape stays
    in lockstep with the CLI / Telegram bot codepath. We persist the
    resulting jti to ``enrollments`` for the agent-side validator.
    """
    if not await user_has_permission(
        db, user, "enroll.create", payload.group_name
    ):
        logger.warning(
            "enroll.create denied by row-level ACL: user=%s role=%s group=%s",
            user.email,
            user.role,
            payload.group_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Missing 'enroll.create' permission for this group. "
                "Ask an admin to grant it via Settings → Users → Permissions."
            ),
        )

    base_url = _safe_base_url()

    token, jti = create_enrollment_token(
        group_name=payload.group_name,
        issued_by=user.email,
        ttl_hours=payload.ttl_hours,
        max_uses=payload.max_uses,
    )

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.ttl_hours)

    enrollment = Enrollment(
        token_jti=jti,
        issued_by=user.email,
        group_name=payload.group_name,
        expires_at=expires_at,
        max_uses=payload.max_uses,
        used_count=0,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)

    install_url = f"{base_url}/install?token={token}"
    install_url_windows = f"{base_url}/install.ps1?token={token}"

    logger.info(
        "enrollment_link_created",
        extra={
            "actor": user.email,
            "group_name": payload.group_name,
            "ttl_hours": payload.ttl_hours,
            "max_uses": payload.max_uses,
            "label": payload.label,
            "token_jti": jti,
        },
    )

    return EnrollLinkOut(
        url=install_url,
        install_url_windows=install_url_windows,
        token=token,
        token_jti=jti,
        group_name=payload.group_name,
        issued_by=user.email,
        expires_at=expires_at,
        expires_in_hours=payload.ttl_hours,
        max_uses=payload.max_uses,
        used_count=0,
        label=payload.label,
    )


@router.get(
    "/links",
    response_model=EnrollLinkListResponse,
)
async def list_enroll_links(
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)] = None,
) -> EnrollLinkListResponse:
    """List enrollment links that are still useful.

    Filters out anything that is expired or has hit ``max_uses`` — since
    revocation works by collapsing those two columns, soft-revoked rows
    disappear here automatically.
    """
    now = datetime.now(timezone.utc)

    # Note: ``used_count < max_uses`` is the same predicate the consume path
    # uses in routers/enroll.py, so what the UI sees matches what would
    # actually be accepted by an agent right now.
    stmt = (
        select(Enrollment)
        .where(Enrollment.expires_at > now)
        .where(Enrollment.used_count < Enrollment.max_uses)
        .order_by(Enrollment.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()

    return EnrollLinkListResponse(
        links=[EnrollLinkSummary.model_validate(row) for row in rows]
    )


@router.delete(
    "/links/{token_jti}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_enroll_link(
    token_jti: str,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
    _admin: Annotated[User, Depends(require_admin)] = None,
) -> Response:
    """Soft-revoke an enrollment link.

    Sets ``expires_at = now()`` and bumps ``used_count`` to ``max_uses`` so
    the row stays around for audit but the agent-side validator refuses to
    accept it.
    """
    stmt = select(Enrollment).where(Enrollment.token_jti == token_jti)
    enrollment = (await db.execute(stmt)).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrollment link {token_jti!r} not found",
        )

    enrollment.expires_at = datetime.now(timezone.utc)
    enrollment.used_count = enrollment.max_uses
    await db.commit()

    logger.info(
        "enrollment_link_revoked",
        extra={
            "actor": user.email,
            "token_jti": token_jti,
            "group_name": enrollment.group_name,
        },
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
