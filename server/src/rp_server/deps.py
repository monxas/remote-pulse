"""FastAPI dependencies for request handling."""
from typing import Annotated

from fastapi import Depends, Header


async def tailscale_identity(
    tailscale_user_login: Annotated[str | None, Header()] = None,
) -> str | None:
    """
    Extract Tailscale identity from headers (F2 implementation).

    F1 STUB: Returns None, no authentication enforced.
    F2 TODO: Uncomment enforcement below when `tailscale serve` is active.

    When behind `tailscale serve`, the header `Tailscale-User-Login` is injected
    by the Tailscale daemon and cannot be spoofed. This is the verified device owner.
    """
    # F2 TODO: Uncomment this block
    # if not tailscale_user_login:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Missing Tailscale identity. Request must come via tailscale serve.",
    #     )
    # return tailscale_user_login

    # F1: No auth enforcement yet
    return tailscale_user_login


TailscaleIdentity = Annotated[str | None, Depends(tailscale_identity)]
