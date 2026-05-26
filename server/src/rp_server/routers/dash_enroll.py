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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rp_server.auth import (
    create_enrollment_token,
    format_short_code,
    generate_short_code,
)
from rp_server.config import settings
from rp_server.database import DbSession
from rp_server.deps import current_user, require_admin
from rp_server.models import Enrollment, User
from rp_server.permissions import user_has_permission


# Default TTL for new short-code links: 5 minutes. The legacy CLI / Telegram
# code path still defaults to the historical 24h via
# :func:`rp_server.auth.create_enrollment_token`'s own default; the dashboard
# is the only entrypoint that opts into the tighter window.
_DEFAULT_TTL_MINUTES: int = 5
# Hard upper bound on operator-chosen TTL: 24h. Above that the install code
# survives long enough to be screenshotted into a chat log and forgotten.
_MAX_TTL_MINUTES: int = 24 * 60
# Number of retries on collision when the partial unique index rejects an
# insert. With ~5.9e8 codes and a tiny live set, the practical bound is 1.
_MAX_SHORT_CODE_RETRIES: int = 5

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

    TTL handling
    ------------
    Two mutually-exclusive fields are accepted for backward / forward compat:

    - ``ttl_minutes`` (preferred, new short-code path): integer minutes, 1..1440.
    - ``ttl_hours``   (legacy): integer hours, 1..24. Kept so older API
      callers (and the on-disk tests covering the previous shape) keep
      working. Anything > 24 is rejected (the historical 720 ceiling was an
      anti-pattern — a 30-day install token is a credential leak waiting
      to happen).

    If neither is provided we default to :data:`_DEFAULT_TTL_MINUTES` (5 min).
    """

    group_name: str = Field(default="default", min_length=1, max_length=63)
    ttl_minutes: int | None = Field(
        default=None,
        ge=1,
        le=_MAX_TTL_MINUTES,
        description=(
            "Magic-link lifetime in minutes (1..1440). Defaults to 5. "
            "Takes precedence over ``ttl_hours`` when both are supplied."
        ),
    )
    ttl_hours: int | None = Field(
        default=None,
        ge=1,
        le=24,
        description=(
            "Legacy lifetime field in hours (1..24). Prefer ``ttl_minutes``. "
            "Capped at 24h — previously this allowed up to 30 days, which "
            "was an unnecessary credential-lifetime risk."
        ),
    )
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

    def resolved_ttl_minutes(self) -> int:
        """Resolve the effective TTL in minutes, honouring precedence rules.

        ``ttl_minutes`` wins over ``ttl_hours`` when both are present. If
        neither is present the default (5 minutes) applies.
        """
        if self.ttl_minutes is not None:
            return self.ttl_minutes
        if self.ttl_hours is not None:
            return self.ttl_hours * 60
        return _DEFAULT_TTL_MINUTES


class EnrollLinkOut(BaseModel):
    """Response body when creating a magic-link.

    The short ``code`` + ``install_url`` are the canonical fields agents
    should use going forward. The long ``url`` / ``token`` / ``install_url_windows``
    are kept for backward compatibility (older UIs, copy-paste recipes,
    and the legacy ``--token=`` path in install.sh) and will be removed
    in a future release.
    """

    model_config = ConfigDict(from_attributes=True)

    # ---- New short-code fields (preferred) ---------------------------------
    code: str = Field(
        description=(
            "Short, memorable enrollment code in display form ``XXX-XXX`` "
            "(e.g. ``K7M-X3F``). Case-insensitive on input; the server "
            "normalises to uppercase and strips dashes before lookup."
        ),
    )
    install_url: str = Field(
        description=(
            "Full, copy-paste-ready install command for the *nix path. "
            "Drops the JWT entirely — only the short code goes over the wire."
        ),
    )
    install_url_windows_short: str = Field(
        description="Same as ``install_url`` but for the PowerShell installer.",
    )

    # ---- Legacy fields (deprecated, kept for backwards compat) -------------
    url: str = Field(
        description=(
            "DEPRECATED — legacy long URL with the JWT embedded as a query "
            "parameter. Prefer ``install_url`` + ``code``. Kept so existing "
            "API consumers don't break."
        ),
    )
    install_url_windows: str = Field(
        description="DEPRECATED — legacy PowerShell variant of ``url``.",
    )
    token: str = Field(
        description=(
            "DEPRECATED — raw JWT. Continues to be a valid credential "
            "(POST /v1/enroll with ``token``) until the legacy path is "
            "removed. Avoid logging or persisting."
        ),
    )

    # ---- Metadata ----------------------------------------------------------
    token_jti: str
    group_name: str
    issued_by: str
    expires_at: datetime
    expires_in_seconds: int
    expires_in_hours: int = Field(
        description=(
            "Whole hours until expiry (rounded down). Retained for "
            "backwards compatibility with the legacy dashboard schema."
        ),
    )
    max_uses: int
    used_count: int = 0
    label: str | None = None


class EnrollLinkSummary(BaseModel):
    """Row in the active-links listing.

    Does NOT include the raw JWT — only the jti is exposed so the UI can
    revoke / display. The token itself is one-shot information that we hand
    out exactly once at creation time.

    The short ``code`` *is* surfaced in display form (``XXX-XXX``) so the
    dashboard table can show the operator-friendly code rather than a
    long URL. The code is no more sensitive than the jti — both are
    one-shot lookup keys gated by the partial unique index and the TTL.
    """

    model_config = ConfigDict(from_attributes=True)

    token_jti: str
    code: str | None = Field(
        default=None,
        description=(
            "Short enrollment code in display form ``XXX-XXX``, or ``null`` "
            "for legacy rows created before alembic 011."
        ),
    )
    install_url_short: str | None = Field(
        default=None,
        description=(
            "Pre-rendered install command using the short code, or ``null`` "
            "for legacy rows."
        ),
    )
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
    ttl_minutes = payload.resolved_ttl_minutes()
    # The JWT helper still talks in hours; pass a float so sub-hour TTLs
    # survive (5 / 60 = 0.0833…). The function rounds via timedelta, so
    # this is safe.
    ttl_hours_float = ttl_minutes / 60.0

    token, jti = create_enrollment_token(
        group_name=payload.group_name,
        issued_by=user.email,
        ttl_hours=ttl_hours_float,
        max_uses=payload.max_uses,
    )

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

    # Retry loop: the partial unique index on ``short_code`` rejects an
    # insert if another active row already has the same canonical code.
    # With 5.9e8 codes and a tiny live set, in practice we never retry,
    # but we still guard against it. ``IntegrityError`` is the asyncpg
    # signal here.
    enrollment: Enrollment | None = None
    canonical_code: str = ""
    last_error: Exception | None = None
    for _attempt in range(_MAX_SHORT_CODE_RETRIES):
        canonical_code = generate_short_code()
        candidate = Enrollment(
            token_jti=jti,
            short_code=canonical_code,
            issued_by=user.email,
            group_name=payload.group_name,
            expires_at=expires_at,
            max_uses=payload.max_uses,
            used_count=0,
        )
        db.add(candidate)
        try:
            await db.commit()
        except IntegrityError as exc:  # pragma: no cover - exercised by collision test
            await db.rollback()
            last_error = exc
            # Re-mint a new short code, keep the same jti — the jti collision
            # would be an entirely different (uuid4) failure mode.
            continue
        await db.refresh(candidate)
        enrollment = candidate
        break

    if enrollment is None:
        logger.error(
            "Failed to allocate unique short code after retries",
            extra={"attempts": _MAX_SHORT_CODE_RETRIES, "error": str(last_error)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not allocate a unique enrollment code. Retry.",
        )

    display_code = format_short_code(canonical_code)
    # Long-URL forms (deprecated but still emitted for back-compat).
    install_url = f"{base_url}/install?token={token}"
    install_url_windows = f"{base_url}/install.ps1?token={token}"
    # New short-code install commands — these are the canonical strings
    # operators copy-paste. ``sh -s --`` ensures argv is passed to the
    # piped script under ``curl … | sh``.
    install_url_short = (
        f"curl {base_url}/install | sh -s -- --code={display_code}"
    )
    install_url_windows_short = (
        f"$env:RP_CODE='{display_code}'; "
        f"iwr -useb {base_url}/install.ps1 | iex"
    )

    # Use the *requested* TTL for expires_in_seconds / expires_in_hours
    # rather than ``(expires_at - now)`` — otherwise a few ms of wall-clock
    # drift between row insert and response serialisation makes the value
    # off-by-one (an operator asking for 12h would see 11h in the response).
    expires_in_seconds = ttl_minutes * 60
    # ``expires_in_hours`` is the field the legacy dashboard consumed; keep
    # it as a rounded-down integer for back-compat. Sub-hour TTLs report 0.
    expires_in_hours = ttl_minutes // 60

    logger.info(
        "enrollment_link_created",
        extra={
            "actor": user.email,
            "group_name": payload.group_name,
            "ttl_minutes": ttl_minutes,
            "max_uses": payload.max_uses,
            "label": payload.label,
            "token_jti": jti,
            # ``short_code`` is logged at issue time but not at consume time
            # (consume only logs the jti). Operators occasionally need to
            # correlate a Telegram screenshot back to an audit row.
            "short_code": canonical_code,
        },
    )

    return EnrollLinkOut(
        code=display_code,
        install_url=install_url_short,
        install_url_windows_short=install_url_windows_short,
        url=install_url,
        install_url_windows=install_url_windows,
        token=token,
        token_jti=jti,
        group_name=payload.group_name,
        issued_by=user.email,
        expires_at=expires_at,
        expires_in_seconds=expires_in_seconds,
        expires_in_hours=expires_in_hours,
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

    base_url = _safe_base_url()
    summaries: list[EnrollLinkSummary] = []
    for row in rows:
        # Rows created before alembic 011 have ``short_code IS NULL``;
        # surface ``code=None`` so the UI can fall back to the legacy URL.
        display = format_short_code(row.short_code) if row.short_code else None
        install_url_short = (
            f"curl {base_url}/install | sh -s -- --code={display}"
            if display
            else None
        )
        summaries.append(
            EnrollLinkSummary(
                token_jti=row.token_jti,
                code=display,
                install_url_short=install_url_short,
                group_name=row.group_name,
                issued_by=row.issued_by,
                expires_at=row.expires_at,
                max_uses=row.max_uses,
                used_count=row.used_count,
                created_at=row.created_at,
            )
        )

    return EnrollLinkListResponse(links=summaries)


@router.delete(
    "/links/{token_jti}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_enroll_link(
    token_jti: str,
    db: DbSession,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    """Soft-revoke an enrollment link.

    Row-level ACL: admins bypass, everyone else needs the
    ``enroll.revoke`` permission scoped to the *enrollment's*
    ``group_name`` (or ``*``). ``enroll.create`` and ``enroll.revoke``
    are separate actions on purpose — an operator may issue links
    without being trusted to revoke them, or vice versa. 404 wins over
    403: we resolve the row first so an operator can't probe for
    arbitrary jtis via the permission check.

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

    if not await user_has_permission(
        db, user, "enroll.revoke", enrollment.group_name
    ):
        logger.warning(
            "enroll.revoke denied by row-level ACL: user=%s role=%s "
            "token_jti=%s group=%s",
            user.email,
            user.role,
            token_jti,
            enrollment.group_name,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Missing 'enroll.revoke' permission for this link's group. "
                "Ask an admin to grant it via Settings → Users → Permissions."
            ),
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
