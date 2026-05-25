"""OIDC authentication flow against PocketID.

Replaces missing forward_auth middleware: we run the full Authorization Code
flow ourselves and persist a signed session cookie via Starlette's
SessionMiddleware. ``current_user`` (deps.py) then resolves the session.

Endpoints:

- ``GET  /auth/login``    Kicks off OIDC: redirect to PocketID with state+nonce.
                           Accepts ``?next=<path>`` to return after login.
- ``GET  /auth/callback`` PocketID redirects here with ``code``+``state``.
                           Exchange for tokens, fetch userinfo, upsert User,
                           persist session, 302 to ``next``.
- ``GET  /auth/logout``   Clear session + redirect to PocketID end-session.
- ``GET  /auth/me``       JSON whoami for debugging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from rp_server.config import settings
from rp_server.database import DbSession
from rp_server.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Single OAuth instance per process. PocketID supports OIDC discovery; we
# register the client lazily because settings are mutable across tests.
_oauth: OAuth | None = None


def _fetch_pocketid_metadata() -> dict:
    """Fetch the OIDC discovery document synchronously at registration time."""
    url = f"{settings.pocketid_base_url}/.well-known/openid-configuration"
    try:
        resp = httpx.get(
            url,
            timeout=10.0,
            follow_redirects=True,
            # PocketID does content negotiation: without an explicit JSON Accept
            # header it returns its SPA HTML shell. Force the API representation.
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        if not resp.text or not resp.text.lstrip().startswith("{"):
            raise RuntimeError(
                f"PocketID discovery returned non-JSON (status={resp.status_code}, "
                f"len={len(resp.text)}, first40={resp.text[:40]!r})"
            )
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch PocketID discovery", exc_info=e, extra={"url": url})
        raise


def get_oauth() -> OAuth:
    """Return the lazily-initialised OAuth client registered with PocketID."""
    global _oauth
    if _oauth is None:
        if not settings.pocketid_client_id or not settings.pocketid_client_secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC client not configured (POCKETID_CLIENT_ID/SECRET missing)",
            )
        metadata = _fetch_pocketid_metadata()
        oauth = OAuth()
        secret = settings.pocketid_client_secret
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        oauth.register(
            name="pocketid",
            client_id=settings.pocketid_client_id,
            client_secret=secret,
            # Pre-load metadata to avoid Authlib's internal fetch (which fails).
            authorize_url=metadata["authorization_endpoint"],
            access_token_url=metadata["token_endpoint"],
            userinfo_endpoint=metadata.get("userinfo_endpoint"),
            jwks_uri=metadata.get("jwks_uri"),
            client_kwargs={"scope": "openid profile email"},
        )
        _oauth = oauth
    return _oauth


@router.get("/login")
async def login(request: Request, next: str = "/dash/"):
    """Start OIDC flow. Caller may pass ``?next=`` to return after auth."""
    # Constrain redirect target to the local host (avoid open redirect).
    if not next.startswith("/"):
        next = "/dash/"
    request.session["oidc_next"] = next

    redirect_uri = str(request.url_for("auth_callback"))
    # Honour proxy host: request.url_for can render an internal IP. Override
    # with the public dashboard origin if configured.
    if settings.public_dashboard_url:
        redirect_uri = f"{settings.public_dashboard_url.rstrip('/')}/auth/callback"

    return await get_oauth().pocketid.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, db: DbSession):
    """Handle PocketID callback: exchange code, upsert user, set session."""
    try:
        token = await get_oauth().pocketid.authorize_access_token(request)
    except OAuthError as e:
        logger.warning("OIDC callback failed", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OIDC auth failed: {e.description or e.error}",
        )

    userinfo = token.get("userinfo") or {}
    if not userinfo:
        # Some IdPs require an explicit /userinfo call.
        userinfo = await get_oauth().pocketid.userinfo(token=token)

    sub = str(userinfo.get("sub") or "")
    email = str(userinfo.get("email") or "").lower()
    name = userinfo.get("name") or userinfo.get("preferred_username")
    if not sub or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OIDC userinfo missing sub or email",
        )

    # Upsert by sub-or-email (matches deps.current_user logic for placeholder seeds).
    stmt = select(User).where((User.pocketid_sub == sub) | (User.email == email))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            pocketid_sub=sub,
            email=email,
            name=name,
            role="viewer",
            accessible_groups=[],
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)
    else:
        if user.pocketid_sub != sub:
            user.pocketid_sub = sub
        if name:
            user.name = name
        user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account disabled",
        )

    # Persist session
    request.session["user_id"] = str(user.id)
    request.session["user_email"] = user.email
    request.session["user_role"] = user.role
    request.session["pocketid_sub"] = sub

    next_path = request.session.pop("oidc_next", "/dash/")
    logger.info(
        "OIDC login success",
        extra={"user_id": str(user.id), "email": user.email, "next": next_path},
    )
    return RedirectResponse(url=next_path, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Clear local session and redirect to PocketID end-session endpoint."""
    request.session.clear()
    end_session = f"{settings.pocketid_base_url}/api/oidc/end-session"
    post_logout = settings.public_dashboard_url or "/"
    params = urlencode({"post_logout_redirect_uri": post_logout})
    return RedirectResponse(url=f"{end_session}?{params}", status_code=302)


@router.get("/me")
async def me(request: Request):
    """Debug whoami: returns whatever is in the session."""
    return JSONResponse(
        {
            "user_id": request.session.get("user_id"),
            "user_email": request.session.get("user_email"),
            "user_role": request.session.get("user_role"),
            "authenticated": bool(request.session.get("user_id")),
        }
    )
