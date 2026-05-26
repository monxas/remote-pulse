"""Settings management endpoints for the SvelteKit dashboard (ADR-0009 Phase 4).

Exposes CRUD over groups + users so admins can manage ACL from the web UI
instead of poking the database directly. All endpoints live under
``/v1/dash/settings/*`` and require ``role=admin`` (see
:func:`rp_server.deps.require_admin`).

Endpoints
---------
- ``GET    /v1/dash/settings/groups``            — list groups + counts
- ``POST   /v1/dash/settings/groups``            — create a new group
- ``DELETE /v1/dash/settings/groups/{name}``     — delete (409 if hosts present)
- ``GET    /v1/dash/settings/users``             — list dashboard users
- ``POST   /v1/dash/settings/users``             — create / invite user
- ``PATCH  /v1/dash/settings/users/{id}``        — update role / accessible_groups
- ``DELETE /v1/dash/settings/users/{id}``        — deactivate user

This is a **scaffold** per ADR-0009 Phase 4. Row-level ACL beyond the
``accessible_groups`` array, audit trail of settings mutations, and
magic-link issuance from the UI are intentionally out of scope and will
be layered on in a follow-up phase.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, select

from rp_server.database import DbSession
from rp_server.deps import require_admin
from rp_server.models import AuditEvent, Group, Host, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/dash/settings", tags=["dash-settings"])


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

# Group names are referenced from ``hosts.group_name`` and the ACL arrays, so
# we keep them in a sane DNS-ish charset. No spaces, no shell metachars.
_GROUP_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-.]{0,62}$")

_ALLOWED_ROLES: frozenset[str] = frozenset({"admin", "operator", "viewer"})


def _validate_group_name(name: str) -> str:
    if not _GROUP_NAME_RE.fullmatch(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid group name. Must start with alphanumeric, "
                "1-63 chars, only [a-zA-Z0-9_.-]."
            ),
        )
    return name


# --------------------------------------------------------------------------- #
# Pydantic schemas
# --------------------------------------------------------------------------- #


class GroupSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    host_count: int
    user_count: int
    auto_distribute_keys: bool = True
    created_at: datetime


class GroupListResponse(BaseModel):
    groups: list[GroupSummary]


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    description: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _GROUP_NAME_RE.fullmatch(v):
            raise ValueError(
                "Group name must start with alphanumeric, 1-63 chars, [a-zA-Z0-9_.-]"
            )
        return v


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Plain ``str`` instead of EmailStr for the response: ``UserCreate``
    # already validates the address on the write path. Re-validating on
    # read would reject historical rows with unusual TLDs (e.g. ``.local``
    # used in test fixtures and small homelab tenants).
    email: str
    name: str | None
    role: str
    groups: list[str] = Field(
        default_factory=list,
        description="Accessible groups (mirrors users.accessible_groups column)",
    )
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class UserListResponse(BaseModel):
    users: list[UserSummary]


class UserCreate(BaseModel):
    # Light-weight email validation: a regex pattern so we accept
    # ``.local`` and other homelab-friendly TLDs that ``EmailStr`` rejects
    # as "special-use or reserved". We still defend against obvious junk.
    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$",
    )
    name: str | None = Field(default=None, max_length=120)
    role: str = Field(default="viewer")
    groups: list[str] = Field(default_factory=list)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in _ALLOWED_ROLES:
            raise ValueError(f"role must be one of {sorted(_ALLOWED_ROLES)}")
        return v

    @field_validator("groups")
    @classmethod
    def _check_groups(cls, v: list[str]) -> list[str]:
        for g in v:
            if not _GROUP_NAME_RE.fullmatch(g):
                raise ValueError(f"invalid group name in groups: {g!r}")
        # de-dupe but preserve order
        seen: set[str] = set()
        out: list[str] = []
        for g in v:
            if g not in seen:
                seen.add(g)
                out.append(g)
        return out


class UserUpdate(BaseModel):
    role: str | None = None
    groups: list[str] | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ALLOWED_ROLES:
            raise ValueError(f"role must be one of {sorted(_ALLOWED_ROLES)}")
        return v

    @field_validator("groups")
    @classmethod
    def _check_groups(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for g in v:
            if not _GROUP_NAME_RE.fullmatch(g):
                raise ValueError(f"invalid group name in groups: {g!r}")
        seen: set[str] = set()
        out: list[str] = []
        for g in v:
            if g not in seen:
                seen.add(g)
                out.append(g)
        return out


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _user_to_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        groups=list(user.accessible_groups or []),
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def _host_count_by_group(db: DbSession) -> dict[str, int]:
    stmt = select(Host.group_name, func.count(Host.id)).group_by(Host.group_name)
    rows = (await db.execute(stmt)).all()
    return {name: int(count) for name, count in rows if name is not None}


async def _user_count_by_group(db: DbSession) -> dict[str, int]:
    """Count active users whose accessible_groups array contains each group name.

    Done in Python rather than SQL because the ACL column is a Postgres
    ``TEXT[]`` and the SQLite test fixture stores it as a JSON-encoded list.
    Doing the unnest in SQL would diverge across dialects; the fan-out is
    bounded by ``COUNT(users) * COUNT(distinct groups in arrays)`` which is
    negligible for a settings page.
    """
    stmt = select(User.accessible_groups).where(User.is_active.is_(True))
    counts: dict[str, int] = {}
    for row in (await db.execute(stmt)).all():
        groups = row[0] or []
        for g in groups:
            counts[g] = counts.get(g, 0) + 1
    return counts


def _emit_audit(
    db: DbSession,
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    payload: dict[str, object] | None = None,
) -> None:
    """Insert an ``audit_events`` row into the current session.

    Caller is responsible for the surrounding ``db.commit()`` — by deferring
    the commit we guarantee the audit row lands atomically with the mutation
    it describes (or rolls back together on error).
    """
    db.add(
        AuditEvent(
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload or {},
        )
    )


# --------------------------------------------------------------------------- #
# Groups endpoints
# --------------------------------------------------------------------------- #


@router.get("/groups", response_model=GroupListResponse)
async def list_groups(
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> GroupListResponse:
    """List all groups with host + user counts."""
    rows = (await db.execute(select(Group).order_by(Group.name))).scalars().all()
    host_counts = await _host_count_by_group(db)
    user_counts = await _user_count_by_group(db)

    groups = [
        GroupSummary(
            name=g.name,
            description=g.description,
            host_count=host_counts.get(g.name, 0),
            user_count=user_counts.get(g.name, 0),
            auto_distribute_keys=g.auto_distribute_keys,
            created_at=g.created_at,
        )
        for g in rows
    ]
    return GroupListResponse(groups=groups)


@router.post(
    "/groups",
    response_model=GroupSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    payload: GroupCreate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> GroupSummary:
    """Create a new group. 409 if name already exists."""
    existing = await db.execute(select(Group).where(Group.name == payload.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group {payload.name!r} already exists",
        )

    group = Group(
        name=payload.name,
        description=payload.description,
        access_users=[],
        auto_distribute_keys=True,
    )
    db.add(group)
    _emit_audit(
        db,
        actor=admin.email,
        action="settings.group.create",
        resource_type="group",
        resource_id=payload.name,
        payload={"name": payload.name, "description": payload.description},
    )
    await db.commit()
    await db.refresh(group)

    logger.info(
        "Group created via dash-settings",
        extra={"group": group.name, "actor": admin.email},
    )

    return GroupSummary(
        name=group.name,
        description=group.description,
        host_count=0,
        user_count=0,
        auto_distribute_keys=group.auto_distribute_keys,
        created_at=group.created_at,
    )


@router.delete(
    "/groups/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_group(
    name: str,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> Response:
    """Delete a group. Returns 409 if any host is still assigned to it.

    Users that reference the group in their ``accessible_groups`` are left
    untouched here — the deletion is intentionally minimal-side-effect.
    A follow-up migration can scrub orphan references.
    """
    _validate_group_name(name)

    group = (
        await db.execute(select(Group).where(Group.name == name))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {name!r} not found",
        )

    host_count = (
        await db.execute(
            select(func.count(Host.id)).where(Host.group_name == name)
        )
    ).scalar_one()
    if host_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Group {name!r} has {host_count} host(s) assigned; "
                "reassign or delete the hosts before deleting the group."
            ),
        )

    await db.execute(delete(Group).where(Group.name == name))
    _emit_audit(
        db,
        actor=admin.email,
        action="settings.group.delete",
        resource_type="group",
        resource_id=name,
        payload={"name": name},
    )
    await db.commit()

    logger.info(
        "Group deleted via dash-settings",
        extra={"group": name, "actor": admin.email},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Users endpoints
# --------------------------------------------------------------------------- #


@router.get("/users", response_model=UserListResponse)
async def list_users(
    db: DbSession,
    _admin: Annotated[User, Depends(require_admin)],
) -> UserListResponse:
    """List all dashboard users (active and inactive)."""
    rows = (
        (await db.execute(select(User).order_by(User.created_at.desc())))
        .scalars()
        .all()
    )
    return UserListResponse(users=[_user_to_summary(u) for u in rows])


async def _validate_group_refs(db: DbSession, names: list[str]) -> None:
    if not names:
        return
    rows = (
        await db.execute(select(Group.name).where(Group.name.in_(names)))
    ).all()
    found = {r[0] for r in rows}
    missing = [n for n in names if n not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown group(s): {missing}",
        )


@router.post(
    "/users",
    response_model=UserSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(
    payload: UserCreate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> UserSummary:
    """Invite / create a dashboard user.

    The real OIDC ``sub`` is unknown until the user actually logs in via
    PocketID, so we seed a ``placeholder-<uuid>`` value. The
    :func:`current_user` dependency rebinds the real sub on first login.
    """
    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User {payload.email!r} already exists",
        )

    await _validate_group_refs(db, payload.groups)

    placeholder_sub = f"placeholder-{uuid.uuid4()}"
    user = User(
        pocketid_sub=placeholder_sub,
        email=payload.email,
        name=payload.name,
        role=payload.role,
        accessible_groups=list(payload.groups),
        is_active=True,
    )
    db.add(user)
    # Flush to allocate the PK before we reference it in the audit row.
    await db.flush()
    _emit_audit(
        db,
        actor=admin.email,
        action="settings.user.create",
        resource_type="user",
        resource_id=str(user.id),
        payload={
            "email": user.email,
            "role": user.role,
            "groups": list(user.accessible_groups or []),
        },
    )
    await db.commit()
    await db.refresh(user)

    logger.info(
        "User created via dash-settings",
        extra={"email": user.email, "role": user.role, "actor": admin.email},
    )
    return _user_to_summary(user)


@router.patch("/users/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> UserSummary:
    """Patch role / accessible_groups / is_active on a user."""
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    # Capture before-state for the audit diff. We snapshot to plain values
    # so subsequent SQLAlchemy attribute mutations don't alias the dict.
    changes: dict[str, dict[str, object]] = {}

    if payload.role is not None:
        # Guard against the last admin demoting themselves into a lockout.
        if user.id == admin.id and payload.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot demote your own admin role.",
            )
        if user.role != payload.role:
            changes["role"] = {"before": user.role, "after": payload.role}
            user.role = payload.role

    if payload.groups is not None:
        await _validate_group_refs(db, payload.groups)
        before_groups = list(user.accessible_groups or [])
        if before_groups != list(payload.groups):
            changes["groups"] = {
                "before": before_groups,
                "after": list(payload.groups),
            }
            user.accessible_groups = list(payload.groups)

    if payload.is_active is not None:
        if user.id == admin.id and payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own account.",
            )
        if user.is_active != payload.is_active:
            changes["is_active"] = {
                "before": user.is_active,
                "after": payload.is_active,
            }
            user.is_active = payload.is_active

    # Only emit an audit row if anything actually changed, otherwise the
    # PATCH is a no-op (e.g. set role to what it already was) and there's
    # nothing to record.
    if changes:
        _emit_audit(
            db,
            actor=admin.email,
            action="settings.user.update",
            resource_type="user",
            resource_id=str(user.id),
            payload={"email": user.email, "changes": changes},
        )

    await db.commit()
    await db.refresh(user)

    logger.info(
        "User updated via dash-settings",
        extra={
            "user_id": str(user.id),
            "role": user.role,
            "actor": admin.email,
        },
    )
    return _user_to_summary(user)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_user(
    user_id: uuid.UUID,
    db: DbSession,
    admin: Annotated[User, Depends(require_admin)],
) -> Response:
    """Delete a dashboard user.

    Refuses to delete the caller's own account to avoid foot-guns. A row-
    level delete is fine here because there are no FKs from other tables
    pointing at ``users.id`` in the current schema.
    """
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    # Stash the email before the delete so the audit payload still carries
    # the human-readable identifier after the row is gone.
    deleted_email = user.email
    await db.execute(delete(User).where(User.id == user_id))
    _emit_audit(
        db,
        actor=admin.email,
        action="settings.user.delete",
        resource_type="user",
        resource_id=str(user_id),
        payload={"email": deleted_email},
    )
    await db.commit()

    logger.info(
        "User deleted via dash-settings",
        extra={"user_id": str(user_id), "actor": admin.email},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
