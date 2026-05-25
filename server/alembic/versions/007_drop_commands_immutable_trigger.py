"""Phase 2.5: drop commands_immutable trigger so the lifecycle works.

The trigger introduced in migration 003 raised on any UPDATE/DELETE to
the ``commands`` table on the theory that commands are an immutable
audit log. That premise was wrong: the row's lifecycle includes

- approval transitions (``human_approved``, ``approved_by``,
  ``rejected_reason``, ``approval_responded_at`` — set after issuance
  when an admin approves/rejects via dashboard or Telegram)
- execution results (``exit_code``, ``stdout``, ``stderr``,
  ``duration_ms``, ``completed_at`` — set when the agent posts back
  via ``POST /v1/agent/commands/{id}/result``)
- the agent claim stamp (``agent_node_id`` — set when an agent first
  pulls the command in ``GET /v1/agent/commands/pending``)

All of those are legitimate post-issuance mutations of the same row.
Real append-only audit (who-did-what-when) lives implicitly in those
column-level timestamps + the synthetic ``/v1/dash/audit`` timeline,
not in trigger-enforced row immutability.

Keep ``commands_truncate_immutable`` — TRUNCATE of the entire table
is still something we never want to allow.

Revision ID: 007
Revises: 006
Create Date: 2026-05-25
"""

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS commands_immutable ON commands;")
    op.execute("DROP FUNCTION IF EXISTS block_command_mutations();")


def downgrade() -> None:
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
