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
from rp_server.models import Enrollment, Host
from rp_server.schemas import AgentConfig, EnrollRequest, EnrollResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["enrollment"])


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
        logger.warning("Invalid enrollment token", exc_info=e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired enrollment token",
        )
    except ValueError as e:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment token not found in database",
        )

    if enrollment.used_count >= enrollment.max_uses:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enrollment token has been exhausted",
        )

    now = datetime.now(timezone.utc)
    if enrollment.expires_at < now:
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

    logger.info(
        "Agent enrolled",
        extra={
            "host_id": str(host.id),
            "hostname": host.hostname,
            "group": host.group_name,
            "enrollment_jti": jti,
        },
    )

    # Return agent config
    agent_config = AgentConfig(
        server_url=settings.server_url,
        heartbeat_interval_s=settings.heartbeat_interval_s,
        # F2 TODO: Add tailscale_authkey here
    )

    return EnrollResponse(host_id=host.id, agent_config=agent_config)
