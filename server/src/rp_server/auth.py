"""JWT enrollment token operations."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from rp_server.config import settings


# --------------------------------------------------------------------------- #
# Short enrollment codes
# --------------------------------------------------------------------------- #
#
# The legacy magic-link embeds a ~250-char JWT in the URL — which leaks into
# Caddy access logs, the agent's shell history and the operator's clipboard
# manager. Short codes replace that surface: 6 characters drawn from a
# confusion-free alphabet, displayed as ``XXX-XXX``. The server normalises
# input to uppercase and strips the dash before lookup.
#
# Alphabet rationale (29 chars):
#   - Drop ``0`` / ``O`` / ``o``    — round-vs-zero confusion.
#   - Drop ``1`` / ``l`` / ``I``    — vertical-bar confusion.
#   - Drop ``S`` / ``5``            — curve-vs-pentagon confusion.
#   - Drop ``Z`` / ``2``? No — ``2`` is kept and ``Z`` is dropped (kept ``2``
#     is the cleaner sans-serif glyph in monospace fonts).
#
# Entropy: 29^6 = 594_823_321 distinct codes (~29.1 bits). At any given moment
# the live set is a handful, so collisions are effectively impossible — but
# we still enforce the DB-level partial unique index (alembic 011) and a
# retry loop on the create path. A 5-minute TTL means the population
# stays tiny.

SHORT_CODE_ALPHABET: str = "ABCDEFGHJKLMNPQRTUVWXY2346789"
SHORT_CODE_LENGTH: int = 6


def generate_short_code() -> str:
    """Generate a fresh 6-char short enrollment code.

    Returned in *canonical* form (no dash, uppercase). Use
    :func:`format_short_code` for display and :func:`normalize_short_code`
    on inbound user input.
    """
    return "".join(
        secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH)
    )


def format_short_code(code: str) -> str:
    """Format a canonical short code for display (``XXXXXX`` → ``XXX-XXX``).

    Idempotent on already-formatted input.
    """
    canonical = normalize_short_code(code)
    if len(canonical) != SHORT_CODE_LENGTH:
        # Best-effort: return as-is so callers don't blow up on legacy rows.
        return canonical
    mid = SHORT_CODE_LENGTH // 2
    return f"{canonical[:mid]}-{canonical[mid:]}"


def normalize_short_code(code: str) -> str:
    """Normalise user input for DB lookup.

    Strips dashes / whitespace and uppercases — both the install scripts
    and the dashboard accept dashed forms (``K7M-X3F``) and lowercase
    (``k7mx3f``) for typing convenience.
    """
    return code.strip().replace("-", "").replace(" ", "").upper()


def create_enrollment_token(
    group_name: str,
    issued_by: str,
    ttl_hours: float = 24,
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
