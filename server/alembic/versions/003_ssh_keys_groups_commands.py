"""SSH keys, groups, commands audit, agent_versions

Revision ID: 003
Revises: 002
Create Date: 2026-05-25

F4-1 schema: groups with access_users array, ssh_keys with fingerprint,
commands immutable audit log with trigger, agent_versions compatibility tracking.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create groups table
    op.create_table(
        "groups",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "access_users",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::TEXT[]"),
        ),
        sa.Column("auto_distribute_keys", sa.Boolean(), server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create ssh_keys table
    op.create_table(
        "ssh_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "host_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("user_name", sa.Text(), nullable=False, server_default=sa.text("'root'")),
        sa.Column("pubkey", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.Text(), unique=True, nullable=False),
        sa.Column("algorithm", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
    )

    op.create_index(
        "idx_ssh_keys_host",
        "ssh_keys",
        ["host_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("idx_ssh_keys_fingerprint", "ssh_keys", ["fingerprint"])

    # Create commands table (immutable audit log)
    op.create_table(
        "commands",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "host_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("issued_by", sa.Text(), nullable=False),
        sa.Column("command_type", sa.Text(), nullable=False),
        sa.Column(
            "command_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("human_approved", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column("server_signature", sa.Text(), nullable=False),
        sa.Column("agent_node_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"]),
    )

    op.create_index(
        "idx_commands_host_issued",
        "commands",
        ["host_id", sa.text("issued_at DESC")],
    )
    op.create_index(
        "idx_commands_issued_by",
        "commands",
        ["issued_by", sa.text("issued_at DESC")],
    )

    # Create immutability trigger for commands
    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_command_mutations() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'commands table is append-only (audit log)';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        CREATE TRIGGER commands_immutable
            BEFORE UPDATE OR DELETE ON commands
            FOR EACH ROW EXECUTE FUNCTION block_command_mutations();
        """
    )

    # Create agent_versions table
    op.create_table(
        "agent_versions",
        sa.Column(
            "host_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("agent_version", sa.Text(), nullable=False),
        sa.Column("api_compat_min", sa.Text(), nullable=False),
        sa.Column("api_compat_max", sa.Text(), nullable=False),
        sa.Column(
            "last_check",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["host_id"], ["hosts.id"], ondelete="CASCADE"),
    )

    # Add FK constraint from hosts.group_name to groups.name
    op.create_foreign_key(
        "hosts_group_fk",
        "hosts",
        "groups",
        ["group_name"],
        ["name"],
        onupdate="CASCADE",
        ondelete="SET NULL",
    )

    # Seed default groups
    op.execute(
        """
        INSERT INTO groups (name, description, access_users, auto_distribute_keys) VALUES
            ('default', 'Default group for unclassified hosts', ARRAY['ramon@monxas.casa'], FALSE),
            ('prod', 'Homelab production hosts (pmx-50, pmx-51, LXCs)', ARRAY['ramon@monxas.casa'], TRUE),
            ('family', 'Family hosts (Carmelo, hermano laptop)', ARRAY['ramon@monxas.casa'], TRUE),
            ('iarq', 'Client iarquitectos.com hosts', ARRAY['ramon@monxas.casa'], TRUE)
        ON CONFLICT (name) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Drop FK constraint first
    op.drop_constraint("hosts_group_fk", "hosts", type_="foreignkey")

    # Drop tables in reverse order
    op.drop_table("agent_versions")

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS commands_immutable ON commands;")
    op.execute("DROP FUNCTION IF EXISTS block_command_mutations();")

    op.drop_index("idx_commands_issued_by", table_name="commands")
    op.drop_index("idx_commands_host_issued", table_name="commands")
    op.drop_table("commands")

    op.drop_index("idx_ssh_keys_fingerprint", table_name="ssh_keys")
    op.drop_index("idx_ssh_keys_host", table_name="ssh_keys")
    op.drop_table("ssh_keys")

    op.drop_table("groups")
