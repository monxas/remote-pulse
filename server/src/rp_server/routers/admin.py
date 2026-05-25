"""Administrative endpoints for groups and system management (F4)."""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_server.database import get_db
from rp_server.deps import TailscaleIdentity, tailscale_identity
from rp_server.models import Group
from rp_server.schemas import GroupCreate, GroupResponse

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/admin/groups", tags=["admin"])


@router.get("", response_model=list[GroupResponse])
async def list_groups(
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> list[GroupResponse]:
    """List all groups.

    Args:
        db: Database session
        identity: Tailscale identity (required)

    Returns:
        List of groups

    Note:
        F5 role enforcement (admin/operator/viewer) is placeholder.
    """
    # TODO: F5 role enforcement
    logger.info("list_groups")

    stmt = select(Group).order_by(Group.name)
    result = await db.execute(stmt)
    groups = result.scalars().all()

    return [GroupResponse.model_validate(group) for group in groups]


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> GroupResponse:
    """Create a new group.

    Args:
        group_data: Group creation payload
        db: Database session
        identity: Tailscale identity (required)

    Returns:
        Created group

    Raises:
        HTTPException: 409 if group already exists

    Note:
        F5 role enforcement (admin only) is placeholder.
    """
    # TODO: F5 admin-only enforcement
    logger.info("create_group", name=group_data.name)

    # Check if group exists
    stmt = select(Group).where(Group.name == group_data.name)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Group {group_data.name} already exists",
        )

    # Create group
    new_group = Group(
        name=group_data.name,
        description=group_data.description,
        access_users=group_data.access_users,
        auto_distribute_keys=group_data.auto_distribute_keys,
    )
    db.add(new_group)
    await db.commit()
    await db.refresh(new_group)

    logger.info("group_created", name=new_group.name)
    return GroupResponse.model_validate(new_group)


@router.patch("/{name}", response_model=GroupResponse)
async def update_group(
    name: str,
    group_data: GroupCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> GroupResponse:
    """Update a group's access_users and settings.

    Args:
        name: Group name
        group_data: Updated group data
        db: Database session
        identity: Tailscale identity (required)

    Returns:
        Updated group

    Raises:
        HTTPException: 404 if group not found

    Note:
        F5 role enforcement (admin only) is placeholder.
    """
    # TODO: F5 admin-only enforcement
    logger.info("update_group", name=name)

    stmt = select(Group).where(Group.name == name)
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {name} not found",
        )

    # Update fields
    if group_data.description is not None:
        group.description = group_data.description
    group.access_users = group_data.access_users
    group.auto_distribute_keys = group_data.auto_distribute_keys

    await db.commit()
    await db.refresh(group)

    logger.info("group_updated", name=name)
    return GroupResponse.model_validate(group)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    identity: Annotated[TailscaleIdentity, Depends(tailscale_identity)],
) -> None:
    """Delete a group.

    Sets all hosts' group_name to NULL (FK ON DELETE SET NULL already configured).

    Args:
        name: Group name
        db: Database session
        identity: Tailscale identity (required)

    Raises:
        HTTPException: 404 if group not found

    Note:
        F5 role enforcement (admin only) is placeholder.
    """
    # TODO: F5 admin-only enforcement
    logger.info("delete_group", name=name)

    stmt = select(Group).where(Group.name == name)
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {name} not found",
        )

    await db.delete(group)
    await db.commit()

    logger.info("group_deleted", name=name)
