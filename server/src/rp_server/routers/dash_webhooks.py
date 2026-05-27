"""Admin CRUD over outbound webhooks (``/v1/dash/webhooks``).

All endpoints require ``role=admin``. The dispatcher itself lives in
:mod:`rp_server.webhooks`; this module is the management surface only.

Secret handling
---------------
The HMAC secret is generated server-side on create and surfaced **once**
in the create response. Subsequent GETs do not include it. Rotation =
delete + recreate (intentional simplicity — the admin can swap the URL's
secret on the receiver side at the same time).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select

from rp_server.database import DbSession
from rp_server.deps import require_admin
from rp_server.events import event_bus
from rp_server.models import AuditEvent, User, Webhook
from rp_server.webhooks import (
    MAX_DELIVERY_HISTORY,
    TEST_EVENT_TYPE,
    generate_secret,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash/webhooks", tags=["dash-webhooks"])


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

_GROUP_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-.]{0,62}$")
# Event filter entries: ``*`` for all, ``<prefix>.`` for prefix match,
# ``<exact>`` otherwise. We constrain to a sane charset to keep the
# filter readable in the admin UI.
_EVENT_FILTER_RE = re.compile(r"^(\*|[a-z][a-z0-9_]*(\.[a-z0-9_]+)*\.?)$")


def _check_event_filter(entries: list[str]) -> list[str]:
    if not entries:
        raise ValueError("event_filter cannot be empty")
    out: list[str] = []
    seen: set[str] = set()
    for e in entries:
        if not _EVENT_FILTER_RE.fullmatch(e):
            raise ValueError(
                f"invalid event_filter entry {e!r}: expected '*', 'prefix.', or 'exact.event'"
            )
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _check_group_filter(entries: list[str] | None) -> list[str] | None:
    if entries is None:
        return None
    if not entries:
        return None  # treat [] same as None
    for g in entries:
        if not _GROUP_NAME_RE.fullmatch(g):
            raise ValueError(f"invalid group name in group_filter: {g!r}")
    # de-dupe
    seen: set[str] = set()
    out: list[str] = []
    for g in entries:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class WebhookSummary(BaseModel):
    """Read response — never includes the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    event_filter: list[str]
    group_filter: list[str] | None = None
    enabled: bool
    created_by: str
    created_at: datetime
    last_fired_at: datetime | None = None
    last_status_code: int | None = None
    last_error: str | None = None
    failure_count: int


class WebhookListResponse(BaseModel):
    webhooks: list[WebhookSummary]


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # https only — http leaks payloads to anyone on-path. We allow http
    # for localhost / internal URLs only via the regex below.
    url: str = Field(min_length=8, max_length=2048)
    event_filter: list[str] = Field(min_length=1)
    group_filter: list[str] | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        # https everywhere, OR http to localhost/127.0.0.1/internal LAN.
        if v.startswith("https://"):
            return v
        if v.startswith("http://"):
            # Permit explicit loopback + RFC1918 for homelab n8n etc. We
            # don't try to be exhaustive; the admin owns this URL.
            tail = v[len("http://") :]
            host = tail.split("/", 1)[0].split(":", 1)[0]
            if (
                host == "localhost"
                or host.startswith("127.")
                or host.startswith("10.")
                or host.startswith("192.168.")
                or host.startswith("172.")
            ):
                return v
        raise ValueError("url must be https (or http to localhost/RFC1918)")

    @field_validator("event_filter")
    @classmethod
    def _check_events(cls, v: list[str]) -> list[str]:
        return _check_event_filter(v)

    @field_validator("group_filter")
    @classmethod
    def _check_groups(cls, v: list[str] | None) -> list[str] | None:
        return _check_group_filter(v)


class WebhookCreateResponse(WebhookSummary):
    """Identical to :class:`WebhookSummary` plus a one-time ``secret`` field.

    Surfaced exactly once on create — the admin must save it client-side
    immediately or rotate (delete + recreate) to get a new one.
    """

    secret: str


class WebhookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=2048)
    event_filter: list[str] | None = None
    group_filter: list[str] | None = None
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return WebhookCreate._check_url(v)

    @field_validator("event_filter")
    @classmethod
    def _check_events(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return _check_event_filter(v)

    @field_validator("group_filter")
    @classmethod
    def _check_groups(cls, v: list[str] | None) -> list[str] | None:
        return _check_group_filter(v)


class WebhookDeliveryEntry(BaseModel):
    delivery_id: str
    event: str
    timestamp: str
    status_code: int | None = None
    error: str | None = None
    attempt: int
    success: bool


class WebhookDeliveriesResponse(BaseModel):
    webhook_id: uuid.UUID
    deliveries: list[WebhookDeliveryEntry]
    max_history: int = MAX_DELIVERY_HISTORY


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _to_summary(row: Webhook) -> WebhookSummary:
    return WebhookSummary(
        id=row.id,
        name=row.name,
        url=row.url,
        event_filter=list(row.event_filter or []),
        group_filter=list(row.group_filter) if row.group_filter else None,
        enabled=bool(row.enabled),
        created_by=row.created_by,
        created_at=row.created_at,
        last_fired_at=row.last_fired_at,
        last_status_code=row.last_status_code,
        last_error=row.last_error,
        failure_count=int(row.failure_count or 0),
    )


def _emit_audit(
    db: DbSession,
    *,
    actor: str,
    action: str,
    resource_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor=actor,
            action=action,
            resource_type="webhook",
            resource_id=resource_id,
            payload=payload or {},
        )
    )


async def _load_or_404(db: DbSession, webhook_id: uuid.UUID) -> Webhook:
    row = (
        await db.execute(select(Webhook).where(Webhook.id == webhook_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook {webhook_id} not found",
        )
    return row


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get("", response_model=WebhookListResponse)
async def list_webhooks(
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> WebhookListResponse:
    rows = (
        (await db.execute(select(Webhook).order_by(Webhook.created_at.desc())))
        .scalars()
        .all()
    )
    return WebhookListResponse(webhooks=[_to_summary(r) for r in rows])


@router.post(
    "",
    response_model=WebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: WebhookCreate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> WebhookCreateResponse:
    """Create a webhook. The secret is returned ONCE in this response."""
    secret = generate_secret()
    row = Webhook(
        name=payload.name,
        url=payload.url,
        secret=secret,
        event_filter=list(payload.event_filter),
        group_filter=list(payload.group_filter) if payload.group_filter else None,
        enabled=True,
        created_by=admin.email,
    )
    db.add(row)
    await db.flush()

    _emit_audit(
        db,
        actor=admin.email,
        action="webhook.created",
        resource_id=str(row.id),
        payload={
            "name": row.name,
            "url": row.url,
            "event_filter": list(row.event_filter or []),
            "group_filter": list(row.group_filter) if row.group_filter else None,
        },
    )
    await db.commit()
    await db.refresh(row)

    summary = _to_summary(row)
    logger.info(
        "Webhook created",
        extra={"webhook_id": str(row.id), "actor": admin.email, "url": row.url},
    )
    return WebhookCreateResponse(**summary.model_dump(), secret=secret)


@router.get("/{webhook_id}", response_model=WebhookSummary)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> WebhookSummary:
    row = await _load_or_404(db, webhook_id)
    return _to_summary(row)


@router.patch("/{webhook_id}", response_model=WebhookSummary)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> WebhookSummary:
    """Patch a webhook. The secret is intentionally NOT updatable."""
    row = await _load_or_404(db, webhook_id)

    changes: dict[str, dict[str, Any]] = {}

    if payload.name is not None and payload.name != row.name:
        changes["name"] = {"before": row.name, "after": payload.name}
        row.name = payload.name
    if payload.url is not None and payload.url != row.url:
        changes["url"] = {"before": row.url, "after": payload.url}
        row.url = payload.url
    if payload.event_filter is not None:
        before = list(row.event_filter or [])
        after = list(payload.event_filter)
        if before != after:
            changes["event_filter"] = {"before": before, "after": after}
            row.event_filter = after
    if payload.group_filter is not None or payload.group_filter == []:
        before_gf = list(row.group_filter) if row.group_filter else None
        after_gf = list(payload.group_filter) if payload.group_filter else None
        if before_gf != after_gf:
            changes["group_filter"] = {"before": before_gf, "after": after_gf}
            row.group_filter = after_gf
    if payload.enabled is not None and payload.enabled != row.enabled:
        changes["enabled"] = {"before": row.enabled, "after": payload.enabled}
        row.enabled = payload.enabled
        # Re-enabling a previously auto-disabled hook resets the failure
        # streak so the next bad delivery doesn't instantly trip the
        # auto-disable threshold again.
        if payload.enabled is True:
            row.failure_count = 0

    if changes:
        _emit_audit(
            db,
            actor=admin.email,
            action="webhook.updated",
            resource_id=str(row.id),
            payload={"changes": changes},
        )

    await db.commit()
    await db.refresh(row)
    return _to_summary(row)


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> Response:
    row = await _load_or_404(db, webhook_id)
    name = row.name
    url = row.url
    await db.execute(delete(Webhook).where(Webhook.id == webhook_id))
    _emit_audit(
        db,
        actor=admin.email,
        action="webhook.deleted",
        resource_id=str(webhook_id),
        payload={"name": name, "url": url},
    )
    await db.commit()
    logger.info(
        "Webhook deleted",
        extra={"webhook_id": str(webhook_id), "actor": admin.email},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_webhook(
    webhook_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    """Fire a synthetic ``webhook.test`` event at this hook only.

    Returns 202 immediately — the delivery is fire-and-forget. The result
    will surface in ``GET /v1/dash/webhooks/{id}/deliveries`` once the
    dispatcher records the outcome.
    """
    row = await _load_or_404(db, webhook_id)

    _emit_audit(
        db,
        actor=admin.email,
        action="webhook.tested",
        resource_id=str(row.id),
        payload={"name": row.name, "url": row.url},
    )
    await db.commit()

    # The dispatcher's subscriber picks this up off the event bus and
    # routes it to exactly this hook via the ``_webhook_id`` marker.
    await event_bus.publish(
        TEST_EVENT_TYPE,
        {
            "_webhook_id": str(row.id),
            "message": "Synthetic webhook.test event",
            "fired_by": admin.email,
        },
    )

    return {
        "status": "queued",
        "webhook_id": str(row.id),
        "event": TEST_EVENT_TYPE,
    }


@router.get(
    "/{webhook_id}/deliveries",
    response_model=WebhookDeliveriesResponse,
)
async def list_deliveries(
    webhook_id: uuid.UUID,
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> WebhookDeliveriesResponse:
    """Return the bounded sliding window of recent delivery attempts."""
    row = await _load_or_404(db, webhook_id)
    entries = [
        WebhookDeliveryEntry(**e) for e in (row.recent_deliveries or [])
    ]
    # Newest first.
    entries.reverse()
    return WebhookDeliveriesResponse(
        webhook_id=row.id,
        deliveries=entries,
        max_history=MAX_DELIVERY_HISTORY,
    )
