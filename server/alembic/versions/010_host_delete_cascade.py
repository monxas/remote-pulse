"""Tighten FK ON DELETE behaviour on ``commands.host_id`` for host deletion.

Companion to the new ``DELETE /v1/dash/hosts/{host_id}`` endpoint
(``host.delete`` permission). Without this migration the row-level FK on
``commands.host_id`` defaults to ``NO ACTION`` and Postgres refuses to
drop a host that has ever issued a command — which, in practice, is every
real host. We swap the constraint to ``ON DELETE CASCADE`` so deleting
a host atomically wipes its command history.

The other host-referencing tables are already set up correctly:

- ``ssh_keys.host_id``       CASCADE (migration 003)
- ``agent_versions.host_id`` CASCADE (migration 003)
- ``canary_deploys.canary_host_id`` SET NULL (migration 006) — kept as-is;
  the endpoint guards against deleting a host with an *active* canary, but
  completed canaries can safely lose their host reference.
- ``heartbeats.host_id`` / ``metric_samples.host_id`` — no FK at all
  (TimescaleDB hypertables). The endpoint deletes those rows explicitly
  before issuing the host delete so we don't leave orphan time-series.
- ``enrollments.used_by_host_id`` — left untouched (post-enroll
  tombstone, not host-owned).

Revision ID: 010
Revises: 009
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # commands.host_id: NO ACTION -> CASCADE
    op.drop_constraint(
        "commands_host_id_fkey",
        "commands",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "commands_host_id_fkey",
        "commands",
        "hosts",
        ["host_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "commands_host_id_fkey",
        "commands",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "commands_host_id_fkey",
        "commands",
        "hosts",
        ["host_id"],
        ["id"],
    )
