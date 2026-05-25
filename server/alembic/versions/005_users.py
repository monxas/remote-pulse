"""Add users table for PocketID OIDC multi-user support

Revision ID: 005
Revises: 003
Create Date: 2026-05-25

F5-1 schema: users table with PocketID OIDC sub, role-based access,
and accessible_groups array for multi-tenant filtering.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("pocketid_sub", sa.Text(), unique=True, nullable=False),
        sa.Column("email", sa.Text(), unique=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "role",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'viewer'"),
        ),
        sa.Column(
            "accessible_groups",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::TEXT[]"),
        ),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'operator', 'viewer')",
            name="users_role_chk",
        ),
    )

    # Create indexes
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_pocketid_sub", "users", ["pocketid_sub"])

    # Seed admin user (Ramón) - placeholder sub will be updated on first login
    op.execute(
        """
        INSERT INTO users (pocketid_sub, email, name, role, accessible_groups)
        VALUES (
            'placeholder-pocketid-sub-ramon',
            'ramon@monxas.casa',
            'Ramón Kamibayashi',
            'admin',
            ARRAY['default', 'prod', 'family', 'iarq']
        )
        ON CONFLICT (email) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("idx_users_pocketid_sub", table_name="users")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
