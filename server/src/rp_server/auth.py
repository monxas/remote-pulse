"""JWT enrollment token operations."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from rp_server.config import settings


def create_enrollment_token(
    group_name: str,
    issued_by: str,
    ttl_hours: int = 24,
    max_uses: int = 1,
) -> tuple[str, str]:
    """
    Create JWT enrollment token.

    Returns:
        Tuple of (token_string, jti) where jti is the unique token identifier.
    """
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=ttl_hours)

    payload: dict[str, Any] = {
        "jti": jti,
        "iat": now,
        "exp": expires_at,
        "group_name": group_name,
        "issued_by": issued_by,
        "max_uses": max_uses,
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, jti


def decode_enrollment_token(token: str) -> dict[str, Any]:
    """
    Decode and validate JWT enrollment token.

    Raises:
        JWTError: If token is invalid, expired, or malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        raise


def validate_token_claims(payload: dict[str, Any]) -> None:
    """
    Validate required JWT claims are present.

    Raises:
        ValueError: If required claims are missing.
    """
    required = {"jti", "group_name", "issued_by", "max_uses"}
    missing = required - set(payload.keys())
    if missing:
        raise ValueError(f"Missing required claims: {missing}")
