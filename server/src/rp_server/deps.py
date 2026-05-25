"""FastAPI dependencies for request handling."""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, EmailStr, HttpUrl
from sqlalchemy import select, update

from rp_server.database import DbSession


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
    db: DbSession,
    x_forwarded_user: Annotated[str | None, Header()] = None,
    x_forwarded_email: Annotated[str | None, Header()] = None,
    x_forwarded_preferred_username: Annotated[str | None, Header()] = None,
):
    """Resolve authenticated user from Caddy forward_auth PocketID headers.

    Caddy injects headers after PocketID OIDC verification:
    - X-Forwarded-User: PocketID subject (sub claim)
    - X-Forwarded-Email: User email
    - X-Forwarded-Preferred-Username: Display name

    On first login, creates user record with default viewer role.
    Updates last_login_at on each request.

    Args:
        db: Database session
        x_forwarded_user: PocketID sub from Caddy
        x_forwarded_email: User email from Caddy
        x_forwarded_preferred_username: Display name from Caddy

    Returns:
        User model instance

    Raises:
        HTTPException 401: If forward_auth headers missing
    """
    from rp_server.models import User

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
    db: DbSession,
    x_forwarded_user: Annotated[str | None, Header()] = None,
    x_forwarded_email: Annotated[str | None, Header()] = None,
    x_forwarded_preferred_username: Annotated[str | None, Header()] = None,
):
    """Optional current_user dependency for dual-mode auth endpoints.

    Returns None if PocketID headers absent (allows Tailscale-only auth).
    """
    if not x_forwarded_user or not x_forwarded_email:
        return None

    return await current_user(
        db=db,
        x_forwarded_user=x_forwarded_user,
        x_forwarded_email=x_forwarded_email,
        x_forwarded_preferred_username=x_forwarded_preferred_username,
    )


async def require_admin(user):
    """Require admin role for endpoint access.

    Args:
        user: Current authenticated user

    Returns:
        User if admin

    Raises:
        HTTPException 403: If user not admin
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user


async def require_operator_or_admin(user):
    """Require operator or admin role for endpoint access.

    Args:
        user: Current authenticated user

    Returns:
        User if operator or admin

    Raises:
        HTTPException 403: If user not operator/admin
    """
    if user.role not in ("admin", "operator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator or admin role required",
        )
    return user
