"""FastAPI dependencies for request handling."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, HttpUrl
from sqlalchemy import select, update

from rp_server.config import settings
from rp_server.database import DbSession

logger = logging.getLogger(__name__)


class TailscaleIdentity(BaseModel):
    """Tailscale identity extracted from headers."""

    login: EmailStr
    name: str | None = None
    node_id: str | None = None
    profile_pic: HttpUrl | None = None


async def tailscale_identity(
    tailscale_user_login: Annotated[str | None, Header()] = None,
    tailscale_user_name: Annotated[str | None, Header()] = None,
    tailscale_user_profile_pic: Annotated[str | None, Header()] = None,
    tailscale_headers: Annotated[str | None, Header()] = None,
) -> TailscaleIdentity:
    """
    Extract Tailscale identity from headers (F2 implementation).

    When behind `tailscale serve`, headers are injected by the Tailscale daemon
    and cannot be spoofed. The `Tailscale-User-Login` header identifies the
    verified device owner in the tailnet.

    Raises:
        HTTPException 401: If Tailscale identity headers are missing.

    Returns:
        TailscaleIdentity with verified user information.
    """
    if not tailscale_user_login:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Request not from tailnet (no Tailscale identity headers)",
        )

    # Extract node_id from Tailscale-Headers if present (format: node=<node_id>)
    node_id = None
    if tailscale_headers:
        for part in tailscale_headers.split(","):
            if part.strip().startswith("node="):
                node_id = part.strip().split("=", 1)[1]
                break

    return TailscaleIdentity(
        login=tailscale_user_login,
        name=tailscale_user_name,
        node_id=node_id,
        profile_pic=tailscale_user_profile_pic if tailscale_user_profile_pic else None,
    )


async def tailscale_identity_optional(
    tailscale_user_login: Annotated[str | None, Header()] = None,
    tailscale_user_name: Annotated[str | None, Header()] = None,
    tailscale_user_profile_pic: Annotated[str | None, Header()] = None,
    tailscale_headers: Annotated[str | None, Header()] = None,
) -> TailscaleIdentity | None:
    """
    Extract Tailscale identity if present, return None if missing.

    For public endpoints (e.g., /v1/enroll) that accept non-tailnet traffic
    during bootstrap phase.

    Returns:
        TailscaleIdentity if headers present, None otherwise.
    """
    if not tailscale_user_login:
        return None

    node_id = None
    if tailscale_headers:
        for part in tailscale_headers.split(","):
            if part.strip().startswith("node="):
                node_id = part.strip().split("=", 1)[1]
                break

    return TailscaleIdentity(
        login=tailscale_user_login,
        name=tailscale_user_name,
        node_id=node_id,
        profile_pic=tailscale_user_profile_pic if tailscale_user_profile_pic else None,
    )


async def current_user(
    request: Request,
    db: DbSession,
    x_forwarded_user: Annotated[str | None, Header()] = None,
    x_forwarded_email: Annotated[str | None, Header()] = None,
    x_forwarded_preferred_username: Annotated[str | None, Header()] = None,
):
    """Resolve authenticated user from Caddy forward_auth PocketID headers.

    Defense against X-Forwarded-* header spoofing (review C3): the request
    must originate from a trusted reverse proxy. We verify either:
        a) client.host is in settings.trusted_proxies (allowlist), OR
        b) `tailscale serve` injected Tailscale-* identity headers, meaning
           the request crossed our Caddy or tsnet wrapper, OR
        c) request explicitly came over the Unix socket / loopback (dev).

    If none of those hold, the X-Forwarded-* headers could have been forged
    by any LAN client → reject 401.

    On first login, creates user record with default viewer role.
    """
    from rp_server.models import User

    # --- Trusted-proxy gate (anti-spoofing) ---
    client_host = request.client.host if request.client else None
    came_via_tailscale = bool(request.headers.get("Tailscale-User-Login"))
    trusted_proxies = set(settings.trusted_proxies or [])
    trusted_proxies.update({"127.0.0.1", "::1"})
    is_trusted_source = client_host in trusted_proxies or came_via_tailscale

    if (x_forwarded_user or x_forwarded_email) and not is_trusted_source:
        logger.warning(
            "Rejected X-Forwarded-* headers from untrusted source",
            extra={
                "client_host": client_host,
                "x_forwarded_user": x_forwarded_user,
                "trusted_proxies": list(trusted_proxies),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Forward-auth headers from untrusted source rejected",
        )

    if not x_forwarded_user or not x_forwarded_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (PocketID forward_auth headers missing)",
        )

    # Look up user by PocketID sub OR email (seed users have placeholder sub
    # until first OIDC login binds the real sub).
    stmt = select(User).where(
        (User.pocketid_sub == x_forwarded_user) | (User.email == x_forwarded_email)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    # Create user on first login (lookup-or-create by sub OR email)
    if not user:
        user = User(
            pocketid_sub=x_forwarded_user,
            email=x_forwarded_email,
            name=x_forwarded_preferred_username,
            role="viewer",
            accessible_groups=[],  # Admin must grant groups
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        # On first OIDC login, bind real PocketID sub to seed user (was placeholder)
        if user.pocketid_sub != x_forwarded_user:
            user.pocketid_sub = x_forwarded_user
            user.name = x_forwarded_preferred_username or user.name
        # Update last login timestamp
        stmt = (
            update(User).where(User.id == user.id).values(last_login_at=datetime.now(timezone.utc))
        )
        await db.execute(stmt)
        await db.commit()
        await db.refresh(user)

    # Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


async def current_user_optional(
    request: Request,
    db: DbSession,
    x_forwarded_user: Annotated[str | None, Header()] = None,
    x_forwarded_email: Annotated[str | None, Header()] = None,
    x_forwarded_preferred_username: Annotated[str | None, Header()] = None,
):
    """Optional current_user dependency for dual-mode auth endpoints.

    Returns None if PocketID headers absent (allows Tailscale-only auth).
    Trusted-proxy enforcement is delegated to current_user().
    """
    if not x_forwarded_user or not x_forwarded_email:
        return None

    return await current_user(
        request=request,
        db=db,
        x_forwarded_user=x_forwarded_user,
        x_forwarded_email=x_forwarded_email,
        x_forwarded_preferred_username=x_forwarded_preferred_username,
    )


async def require_admin(user=Depends(current_user)):
    """Dependency: caller must have role=admin."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin role required (current role: {user.role})",
        )
    return user


async def require_operator_or_admin(user=Depends(current_user)):
    """Dependency: caller must have role=admin or role=operator."""
    if user.role not in ("admin", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Operator+ role required (current role: {user.role})",
        )
    return user


# (Older stub variants of require_admin/require_operator_or_admin removed;
# canonical definitions live above with `Depends(current_user)`.)
