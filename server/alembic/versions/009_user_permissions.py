"""Add user_permissions table for row-level per-action ACL.

Companion to ``users.role`` (admin / operator / viewer) and
``users.accessible_groups`` (group-level visibility): this table stores
explicit grants of fine-grained actions (e.g. ``command.issue``,
``command.approve``, ``host.delete``, ``enroll.create``) scoped to a group
name pattern (or ``*`` for "anywhere"). Admins remain implicitly granted
every action; non-admins only get what's explicitly listed here.

Rows are created via ``POST /v1/dash/settings/users/{id}/permissions`` and
the mutation is audited through the same ``audit_events`` log that already
records settings changes (see migration 008).

Revision ID: 009
Revises: 008
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'*'"),
        ),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "action",
            "scope",
            name="user_permissions_user_action_scope_uq",
        ),
    )

    op.create_index(
        "idx_user_permissions_user",
        "user_permissions",
        ["user_id"],
    )
    op.create_index(
        "idx_user_permissions_action",
        "user_permissions",
        ["action"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_permissions_action", table_name="user_permissions")
    op.drop_index("idx_user_permissions_user", table_name="user_permissions")
    op.drop_table("user_permissions")
