"""FastAPI dependencies for request handling."""

from typing import Annotated

from fastapi import Header, HTTPException, status
from pydantic import BaseModel, EmailStr, HttpUrl


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
