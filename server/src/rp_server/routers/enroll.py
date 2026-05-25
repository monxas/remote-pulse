"""Enrollment endpoint for agent onboarding."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from rp_server.auth import decode_enrollment_token, validate_token_claims
from rp_server.config import settings
from rp_server.database import DbSession
from rp_server.integrations.tailscale_api import (
    TailscaleAPIClient,
    TailscaleAPIError,
)
from rp_server.models import Enrollment, Host
from rp_server.schemas import AgentConfig, EnrollRequest, EnrollResponse
from rp_server.signing import ServerSigningKey
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["enrollment"])

# Module-level server signing key (loaded once)
_server_signing_key: ServerSigningKey | None = None


def get_server_signing_key() -> ServerSigningKey:
    """Get or initialize server signing key."""
    global _server_signing_key
    if _server_signing_key is None:
        _server_signing_key = ServerSigningKey.load_or_generate()
    return _server_signing_key


@router.post("/enroll", response_model=EnrollResponse, status_code=status.HTTP_201_CREATED)
async def enroll_agent(request: EnrollRequest, db: DbSession) -> EnrollResponse:
    """
    Enroll a new agent.

    Process:
    1. Validate JWT enrollment token
    2. Check token not expired and not exhausted (used_count < max_uses)
    3. Create host record
    4. Mark enrollment as used
    5. Return host_id and agent config

    F1: Returns basic config without Tailscale authkey.
    F2 TODO: Generate and return ephemeral Tailscale authkey.
    """
    # Decode and validate JWT
    try:
        payload = decode_enrollment_token(request.token)
        validate_token_claims(payload)
    except JWTError as e:
        from rp_server.metrics_exporter import record_enroll_failure

        record_enroll_failure("unknown", "invalid_token")
        logger.warning("Invalid enrollment token", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired enrollment token",
        )
    except ValueError as e:
        from rp_server.metrics_exporter import record_enroll_failure

        record_enroll_failure("unknown", "missing_claims")
        logger.warning("Token missing required claims", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    jti = payload["jti"]
    token_group = payload["group_name"]

    # Check enrollment record exists and is valid
    # (max_uses lives in DB row, not trusted from token claims)
    stmt = select(Enrollment).where(Enrollment.token_jti == jti)
    result = await db.execute(stmt)
    enrollment = result.scalar_one_or_none()

    if not enrollment:
        from rp_server.metrics_exporter import record_enroll_failure

        record_enroll_failure(token_group, "token_not_found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment token not found in database",
        )

    if enrollment.used_count >= enrollment.max_uses:
        from rp_server.metrics_exporter import record_enroll_failure

        record_enroll_failure(token_group, "token_exhausted")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enrollment token has been exhausted",
        )

    now = datetime.now(timezone.utc)
    if enrollment.expires_at < now:
        from rp_server.metrics_exporter import record_enroll_failure

        record_enroll_failure(token_group, "token_expired")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enrollment token has expired",
        )

    # Create host record
    host = Host(
        hostname=request.hostname,
        os=request.os,
        arch=request.arch,
        distro=request.distro,
        agent_version=request.agent_version,
        group_name=request.group or token_group,
        metadata={"host_fingerprint": request.host_fingerprint},
    )

    db.add(host)

    try:
        await db.flush()
    except IntegrityError as e:
        logger.error("Failed to create host", exc_info=e)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Host with this fingerprint may already exist",
        )

    # Update enrollment usage
    enrollment.used_count += 1
    if enrollment.used_by_host_id is None:
        enrollment.used_by_host_id = host.id

    await db.commit()

    # F2: Generate Tailscale ephemeral auth-key
    tailscale_authkey = None
    if settings.tailscale_api_key:
        # Map group to Tailscale tag
        group_tag = settings.tailscale_tags_by_group.get(
            host.group_name or "default",
            settings.tailscale_tags_by_group.get("default", "tag:rp-agent-default"),
        )

        try:
            ts_client = TailscaleAPIClient(
                api_key=settings.tailscale_api_key.get_secret_value(),
                tailnet=settings.tailscale_tailnet,
            )

            ts_response = await ts_client.create_authkey(
                ephemeral=True,
                reusable=False,
                preauthorized=True,
                expiry_seconds=settings.tailscale_authkey_expiry_seconds,
                tags=[group_tag],
                # Tailscale rejects ':' and '+' in descriptions, so use a safe format.
                description=f"rp enroll {host.hostname} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H%M%S UTC')}",
            )

            tailscale_authkey = ts_response.key

            logger.info(
                "Tailscale auth-key generated",
                extra={
                    "host_id": str(host.id),
                    "hostname": host.hostname,
                    "tag": group_tag,
                    "key_id": ts_response.id,
                },
            )

        except TailscaleAPIError as e:
            # Log error but don't fail enrollment (F1-degraded mode)
            logger.warning(
                "Failed to generate Tailscale auth-key, continuing in degraded mode",
                extra={
                    "host_id": str(host.id),
                    "hostname": host.hostname,
                    "error": str(e),
                },
            )
    else:
        logger.warning(
            "Tailscale API key not configured, enrollment without auth-key",
            extra={"host_id": str(host.id), "hostname": host.hostname},
        )

    logger.info(
        "Agent enrolled",
        extra={
            "host_id": str(host.id),
            "hostname": host.hostname,
            "group": host.group_name,
            "enrollment_jti": jti,
            "tailscale_authkey_issued": tailscale_authkey is not None,
        },
    )

    # Record metrics
    from rp_server.metrics_exporter import record_enroll_success

    record_enroll_success(host.group_name or "default")

    # Get server signing key for distribution
    signing_key = get_server_signing_key()

    # Return agent config (with server pubkey for command verification)
    agent_config = AgentConfig(
        server_url=settings.server_url,
        heartbeat_interval_s=settings.heartbeat_interval_s,
        tailscale_authkey=tailscale_authkey,
        server_pubkey=signing_key.public_key_pem(),
        server_pubkey_fingerprint=signing_key.public_key_fingerprint(),
    )

    return EnrollResponse(host_id=host.id, agent_config=agent_config)


class ReauthRequest(BaseModel):
    """Re-authentication request for DR scenarios."""

    host_id: str
    last_known_server_pubkey: str | None = None
    machine_fingerprint: str


class ReauthResponse(BaseModel):
    """Re-authentication response with new Tailscale auth-key."""

    tailscale_authkey: str | None = None
    status: str


@router.post("/agent/reauth", response_model=ReauthResponse)
async def reauth_agent(request: ReauthRequest, db: DbSession) -> ReauthResponse:
    """
    Re-authenticate agent after server restore or DR event.

    F2: Placeholder validation + new auth-key issuance.
    F8: Complete DR logic (pubkey rotation, fingerprint validation).

    Args:
        request: Host ID and machine fingerprint for validation

    Returns:
        New Tailscale ephemeral auth-key if configured
    """
    import uuid

    try:
        host_uuid = uuid.UUID(request.host_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid host_id format",
        )

    # Verify host exists
    stmt = select(Host).where(Host.id == host_uuid)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()

    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {request.host_id} not found",
        )

    # F2: Basic validation only (fingerprint match check deferred to F8)
    logger.info(
        "Agent reauth requested",
        extra={
            "host_id": str(host.id),
            "hostname": host.hostname,
            "machine_fingerprint": request.machine_fingerprint,
        },
    )

    # Generate new Tailscale auth-key
    tailscale_authkey = None
    if settings.tailscale_api_key:
        group_tag = settings.tailscale_tags_by_group.get(
            host.group_name or "default",
            settings.tailscale_tags_by_group.get("default", "tag:rp-agent-default"),
        )

        try:
            ts_client = TailscaleAPIClient(
                api_key=settings.tailscale_api_key.get_secret_value(),
                tailnet=settings.tailscale_tailnet,
            )

            ts_response = await ts_client.create_authkey(
                ephemeral=True,
                reusable=False,
                preauthorized=True,
                expiry_seconds=settings.tailscale_authkey_expiry_seconds,
                tags=[group_tag],
                description=f"rp reauth {host.hostname} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H%M%S UTC')}",
            )

            tailscale_authkey = ts_response.key

            logger.info(
                "Tailscale auth-key generated for reauth",
                extra={
                    "host_id": str(host.id),
                    "hostname": host.hostname,
                    "tag": group_tag,
                },
            )

        except TailscaleAPIError as e:
            logger.error(
                "Failed to generate Tailscale auth-key for reauth",
                extra={"host_id": str(host.id), "error": str(e)},
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate authentication key",
            )

    return ReauthResponse(
        tailscale_authkey=tailscale_authkey,
        status="ok",
    )
