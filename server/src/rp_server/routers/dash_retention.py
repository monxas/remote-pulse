"""Admin surface for the audit-events retention policy.

Three endpoints, all admin-only:

* ``GET  /v1/dash/settings/retention``           — read the singleton policy.
* ``PATCH /v1/dash/settings/retention``          — update days / enabled.
* ``POST /v1/dash/settings/retention/purge-now`` — fire an immediate
  purge cycle (synchronously; returns the number deleted).

The dispatcher loop in :mod:`rp_server.audit_retention` does the same
work on a 24h tick, but the manual button is the difference between an
admin trusting the system and an admin watching ``audit_events`` grow
all weekend wondering if the schedule is actually working.

Every mutation lands in ``audit_events`` itself — meta, yes, but
necessary: the retention policy is part of the trust model and changes
to it should be visible in the same place every other settings change
lands.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from rp_server.audit_retention import (
    MAX_RETENTION_DAYS,
    MIN_RETENTION_DAYS,
    get_config,
    purge_old_audit_events,
    update_config,
)
from rp_server.database import DbSession
from rp_server.deps import require_admin
from rp_server.models import AuditEvent, User

logger = logging.getLogger(__name__)

# Mounted under the existing ``/v1/dash/settings/...`` namespace so the
# admin SPA can colocate retention with groups + users without changing
# the URL story.
router = APIRouter(
    prefix="/v1/dash/settings/retention",
    tags=["dash-retention"],
)


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class RetentionConfigResponse(BaseModel):
    """Current state of the retention policy + bounds for client validation.

    Exposing ``min_days`` / ``max_days`` in the response lets the SPA
    render the input control without hard-coding the bounds — they
    stay in one place (``audit_retention.py``).
    """

    model_config = ConfigDict(from_attributes=True)

    retention_days: int
    enabled: bool
    last_purge_at: datetime | None
    last_purge_count: int | None
    updated_by: str
    updated_at: datetime
    min_days: int = MIN_RETENTION_DAYS
    max_days: int = MAX_RETENTION_DAYS


class RetentionConfigUpdate(BaseModel):
    """PATCH body — both fields optional; at least one must be present.

    ``retention_days`` is validated against the same bounds the
    background loop enforces (``MIN_RETENTION_DAYS`` /
    ``MAX_RETENTION_DAYS``). FastAPI returns 422 on violation — the
    update_config helper would also reject it but FastAPI's framing is
    nicer for the client.
    """

    retention_days: int | None = Field(
        default=None,
        ge=MIN_RETENTION_DAYS,
        le=MAX_RETENTION_DAYS,
    )
    enabled: bool | None = None


class PurgeNowResponse(BaseModel):
    deleted: int
    retention_days: int
    enabled: bool


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _emit_audit(
    db: DbSession,
    *,
    actor: str,
    action: str,
    payload: dict[str, Any],
) -> None:
    """Record a retention-config mutation in the audit log.

    ``resource_type`` / ``resource_id`` follow the convention used by
    the other settings routers — ``"retention_config"`` + ``"singleton"``
    so the audit timeline UI can still group + filter sanely.
    """
    db.add(
        AuditEvent(
            actor=actor,
            action=action,
            resource_type="retention_config",
            resource_id="singleton",
            payload=payload,
        )
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("", response_model=RetentionConfigResponse)
async def read_retention(
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> RetentionConfigResponse:
    config = await get_config(db)
    # ``get_config`` may have inserted the missing seed row; commit so
    # subsequent GETs don't recreate it.
    await db.commit()
    return RetentionConfigResponse.model_validate(config)


@router.patch("", response_model=RetentionConfigResponse)
async def patch_retention(
    payload: RetentionConfigUpdate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> RetentionConfigResponse:
    if payload.retention_days is None and payload.enabled is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of retention_days / enabled must be supplied",
        )

    # Snapshot before-state for the audit row — easier to diff in the
    # UI than reconstructing it from two separate audit entries.
    before = await get_config(db)
    before_snap = {
        "retention_days": before.retention_days,
        "enabled": before.enabled,
    }

    try:
        row = await update_config(
            db,
            actor=admin.email,
            retention_days=payload.retention_days,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        # Defensive — Field() validators above should already have
        # caught this, but in case the bounds change asymmetrically
        # between this layer and the service layer we still want a
        # clean 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    after_snap = {
        "retention_days": row.retention_days,
        "enabled": row.enabled,
    }
    changes = {
        k: {"before": before_snap[k], "after": after_snap[k]}
        for k in after_snap
        if before_snap[k] != after_snap[k]
    }
    if changes:
        _emit_audit(
            db,
            actor=admin.email,
            action="audit.retention.config_updated",
            payload={"changes": changes},
        )

    await db.commit()
    await db.refresh(row)
    logger.info(
        "audit retention config updated",
        extra={"actor": admin.email, "changes": list(changes.keys())},
    )
    return RetentionConfigResponse.model_validate(row)


@router.post("/purge-now", response_model=PurgeNowResponse)
async def purge_now(
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> PurgeNowResponse:
    """Trigger an immediate purge cycle.

    The audit row for ``audit.retention.manual_purge`` is emitted
    BEFORE the delete so the act of triggering survives even if the
    purge somehow blew up mid-flight — i.e. the trail of who-pressed-
    the-button is durable independent of the outcome.
    """
    config = await get_config(db)

    _emit_audit(
        db,
        actor=admin.email,
        action="audit.retention.manual_purge",
        payload={
            "retention_days": config.retention_days,
            "enabled": config.enabled,
        },
    )
    # Commit the audit row first so the next call (which itself
    # commits) doesn't lose it on rollback.
    await db.commit()

    deleted = await purge_old_audit_events(db, config=config)

    logger.info(
        "manual audit retention purge",
        extra={"actor": admin.email, "deleted": deleted},
    )
    return PurgeNowResponse(
        deleted=deleted,
        retention_days=config.retention_days,
        enabled=config.enabled,
    )
