"""SSH key lifecycle endpoints (F4)."""

import base64
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.database import get_db
from rp_server.deps import TailscaleIdentity, tailscale_identity, tailscale_identity_optional
from rp_server.models import Group, Host, SSHKey
from rp_server.schemas import SSHKeyRegister, SSHKeyResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/keys", tags=["keys"])


def compute_ssh_fingerprint(pubkey: str) -> str:
    """Compute SHA256 fingerprint from SSH pubkey.

    Args:
        pubkey: Full SSH public key (e.g., "ssh-ed25519 AAAA... comment")

    Returns:
        Fingerprint in format "SHA256:base64hash"

    Raises:
        ValueError: If pubkey format is invalid
    """
    try:
        parts = pubkey.strip().split()
        if len(parts) < 2:
            raise ValueError("Invalid pubkey format: expected at least algorithm and blob")

        # Decode base64 blob
        blob = base64.b64decode(parts[1])

        # Compute SHA256
        digest = hashlib.sha256(blob).digest()

        # Encode to base64 without padding
        b64 = base64.b64encode(digest).decode("ascii").rstrip("=")

        return f"SHA256:{b64}"
    except Exception as e:
        raise ValueError(f"Failed to compute fingerprint: {e}") from e


async def trigger_webhook(event: str, payload: dict) -> None:
    """Trigger n8n webhook for key lifecycle events.

    Args:
        event: Event name (key_registered, key_revoked, etc.)
        payload: Event data

    Note:
        No-op if webhook URL not configured. Real implementation will use httpx.
    """
    # TODO: Implement webhook trigger when n8n endpoint configured
    logger.info("webhook_stub", event=event, payload=payload)


@router.post("", response_model=SSHKeyResponse, status_code=status.HTTP_201_CREATED)
async def register_ssh_key(
    key_data: SSHKeyRegister,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)],
) -> SSHKeyResponse:
    """Register SSH public key for a host.

    Agent generates ed25519 keypair locally and registers the pubkey with the server.
    If fingerprint already exists but revoked, re-registers (clears revoked_at).
    If exists and not revoked, returns 409 conflict.

    Args:
        key_data: SSH key registration payload
        db: Database session
        identity: Optional Tailscale identity (degraded F1 mode)

    Returns:
        Registered SSH key response

    Raises:
        HTTPException: 404 if host not found, 409 if key already registered, 400 if fingerprint mismatch
    """
    logger.info(
        "register_ssh_key_request",
        host_id=str(key_data.host_id),
        user=key_data.user_name,
        fingerprint=key_data.fingerprint,
    )

    # Validate host exists
    stmt = select(Host).where(Host.id == key_data.host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {key_data.host_id} not found",
        )

    # Compute and validate fingerprint
    computed_fp = compute_ssh_fingerprint(key_data.pubkey)
    if computed_fp != key_data.fingerprint:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Fingerprint mismatch: provided={key_data.fingerprint}, computed={computed_fp}",
        )

    # Check if key already exists
    stmt = select(SSHKey).where(SSHKey.fingerprint == key_data.fingerprint)
    result = await db.execute(stmt)
    existing_key = result.scalar_one_or_none()

    if existing_key:
        if existing_key.revoked_at is None:
            # Already registered and active
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Key with fingerprint {key_data.fingerprint} already registered and active",
            )
        else:
            # Previously revoked, re-register
            logger.info(
                "re_registering_revoked_key",
                fingerprint=key_data.fingerprint,
                previous_revoked_at=existing_key.revoked_at,
            )
            existing_key.revoked_at = None
            existing_key.revoked_reason = None
            existing_key.pubkey = key_data.pubkey  # Update in case it changed
            existing_key.user_name = key_data.user_name
            await db.commit()
            await db.refresh(existing_key)
            await trigger_webhook("key_re_registered", {"fingerprint": key_data.fingerprint})
            return SSHKeyResponse.model_validate(existing_key)

    # Create new key
    new_key = SSHKey(
        host_id=key_data.host_id,
        user_name=key_data.user_name,
        pubkey=key_data.pubkey,
        fingerprint=key_data.fingerprint,
        algorithm=key_data.algorithm,
    )
    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)

    logger.info("ssh_key_registered", key_id=str(new_key.id), fingerprint=new_key.fingerprint)
    await trigger_webhook(
        "key_registered", {"fingerprint": key_data.fingerprint, "host_id": str(key_data.host_id)}
    )

    return SSHKeyResponse.model_validate(new_key)


@router.get("", response_model=list[SSHKeyResponse])
async def list_ssh_keys(
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
    host_id: Annotated[uuid.UUID | None, Query()] = None,
    group: Annotated[str | None, Query()] = None,
    include_revoked: Annotated[bool, Query()] = False,
) -> list[SSHKeyResponse]:
    """List SSH keys with optional filters.

    Args:
        db: Database session
        identity: Tailscale identity (required)
        host_id: Filter by host ID
        group: Filter by group name (hosts in that group)
        include_revoked: Include revoked keys

    Returns:
        List of SSH keys

    Note:
        F5 role enforcement (admin/operator/viewer) is a placeholder for now.
    """
    # TODO: F5 role enforcement
    logger.info("list_ssh_keys", host_id=str(host_id) if host_id else None, group=group)

    stmt = select(SSHKey)

    # Filter by host_id
    if host_id:
        stmt = stmt.where(SSHKey.host_id == host_id)

    # Filter by group
    if group:
        # Join with hosts to filter by group_name
        stmt = stmt.join(Host, SSHKey.host_id == Host.id).where(Host.group_name == group)

    # Filter revoked
    if not include_revoked:
        stmt = stmt.where(SSHKey.revoked_at.is_(None))

    stmt = stmt.order_by(SSHKey.created_at.desc())

    result = await db.execute(stmt)
    keys = result.scalars().all()

    return [SSHKeyResponse.model_validate(key) for key in keys]


@router.delete("/{fingerprint}", response_model=SSHKeyResponse)
async def revoke_ssh_key(
    fingerprint: str,
    reason: Annotated[str, Query(min_length=1)],
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> SSHKeyResponse:
    """Revoke an SSH key.

    Marks the key as revoked (soft delete for audit). Next distribute will omit this key.

    Args:
        fingerprint: SSH key fingerprint (SHA256:...)
        reason: Reason for revocation
        db: Database session
        identity: Tailscale identity (required)

    Returns:
        Updated SSH key response

    Raises:
        HTTPException: 404 if key not found
    """
    # TODO: F5 role enforcement (admin only)
    logger.info("revoke_ssh_key", fingerprint=fingerprint, reason=reason)

    stmt = select(SSHKey).where(SSHKey.fingerprint == fingerprint)
    result = await db.execute(stmt)
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Key with fingerprint {fingerprint} not found",
        )

    if key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Key {fingerprint} already revoked at {key.revoked_at}",
        )

    # Mark as revoked
    key.revoked_at = datetime.now(timezone.utc)
    key.revoked_reason = reason
    await db.commit()
    await db.refresh(key)

    logger.info("ssh_key_revoked", fingerprint=fingerprint, reason=reason)
    await trigger_webhook("key_revoked", {"fingerprint": fingerprint, "reason": reason})

    return SSHKeyResponse.model_validate(key)


@router.post("/distribute/{group}")
async def distribute_keys(
    group: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> dict:
    """Generate authorized_keys content for all hosts in a group.

    Aggregates all active SSH keys from hosts in the group.
    Future F5 will add human access_users keys.

    Args:
        group: Group name
        db: Database session
        identity: Tailscale identity (required)

    Returns:
        Dict with group, content, host_count, generated_at

    Raises:
        HTTPException: 404 if group not found
    """
    # TODO: F5 role enforcement (admin/operator only)
    logger.info("distribute_keys", group=group)

    # Validate group exists
    stmt = select(Group).where(Group.name == group)
    result = await db.execute(stmt)
    group_obj = result.scalar_one_or_none()
    if not group_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {group} not found",
        )

    # Get all hosts in group
    stmt = select(Host).where(Host.group_name == group)
    result = await db.execute(stmt)
    hosts = result.scalars().all()

    if not hosts:
        logger.warning("distribute_keys_no_hosts", group=group)
        return {
            "group": group,
            "content": "",
            "host_count": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # Get all active SSH keys for these hosts
    host_ids = [h.id for h in hosts]
    stmt = select(SSHKey).where(SSHKey.host_id.in_(host_ids), SSHKey.revoked_at.is_(None))
    result = await db.execute(stmt)
    keys = result.scalars().all()

    # Generate authorized_keys content
    lines = []
    for key in keys:
        # Format: pubkey + comment
        comment = f"rp-managed-{key.user_name}@{key.host_id}"
        lines.append(f"{key.pubkey.strip()} {comment}")

    content = "\n".join(lines)

    logger.info("keys_distributed", group=group, host_count=len(hosts), key_count=len(keys))

    return {
        "group": group,
        "content": content,
        "host_count": len(hosts),
        "key_count": len(keys),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/authorized/{host_id}")
async def get_authorized_keys(
    host_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity | None, Depends(tailscale_identity_optional)],
) -> dict:
    """Get authorized_keys content for a specific host.

    Agent polls this endpoint and only writes if sha256 differs (idempotent).

    Args:
        host_id: Host UUID
        db: Database session
        identity: Optional Tailscale identity

    Returns:
        Dict with content and sha256 hash

    Raises:
        HTTPException: 404 if host not found
    """
    logger.info("get_authorized_keys", host_id=str(host_id))

    # Validate host exists and get its group
    stmt = select(Host).where(Host.id == host_id)
    result = await db.execute(stmt)
    host = result.scalar_one_or_none()
    if not host:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host {host_id} not found",
        )

    if not host.group_name:
        # Host not in any group, return empty
        return {"content": "", "sha256": hashlib.sha256(b"").hexdigest()}

    # Get all active keys for hosts in the same group
    stmt = (
        select(SSHKey)
        .join(Host, SSHKey.host_id == Host.id)
        .where(Host.group_name == host.group_name, SSHKey.revoked_at.is_(None))
    )
    result = await db.execute(stmt)
    keys = result.scalars().all()

    # Generate authorized_keys content
    lines = []
    for key in keys:
        comment = f"rp-managed-{key.user_name}@{key.host_id}"
        lines.append(f"{key.pubkey.strip()} {comment}")

    content = "\n".join(lines)
    if content:
        content += "\n"  # Trailing newline

    # Compute SHA256
    sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    logger.info(
        "authorized_keys_generated", host_id=str(host_id), key_count=len(keys), sha256=sha256_hash
    )

    return {"content": content, "sha256": sha256_hash}
