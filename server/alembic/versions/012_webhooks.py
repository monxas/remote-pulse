"""Add ``webhooks`` table for outbound event delivery.

Backs the webhook subscription feature: admins register a URL + HMAC
secret + event filter, and the in-process ``WebhookDispatcher``
broadcasts matching events to those URLs as signed JSON POSTs. See
``rp_server.webhooks`` for the dispatcher implementation and
``rp_server.routers.dash_webhooks`` for the CRUD surface.

Why a single table (no separate ``webhook_deliveries``)
-------------------------------------------------------
A full delivery log table would explode in cardinality (events x
endpoints) for what is, at homelab scale, a debugging aid more than a
load-bearing audit. We instead keep the last N delivery results in a
JSONB sliding window on the row itself (``recent_deliveries``). This is
bounded by the dispatcher to ``MAX_DELIVERY_HISTORY`` entries and is
sufficient for the "show me the last few attempts to this URL" UX while
keeping the schema flat. The high-level audit trail (create / update /
delete / test) still lands in ``audit_events``.

Revision ID: 012
Revises: 011
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        # Stored in cleartext (the admin who created it owns rotation).
        # The webhook receiver verifies HMAC-SHA256 over the body so the
        # secret never travels with the delivery itself.
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column(
            "event_filter",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "group_filter",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_fired_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "failure_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # JSONB sliding window of the last ~20 delivery attempts. See module
        # docstring for the trade-off vs a dedicated table.
        sa.Column(
            "recent_deliveries",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # Partial index — the dispatcher's hot path is "scan enabled webhooks
    # matching this event_type", so a partial index on the boolean keeps
    # the index small (disabled rows fall out entirely).
    op.create_index(
        "idx_webhooks_enabled",
        "webhooks",
        ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )


def downgrade() -> None:
    op.drop_index("idx_webhooks_enabled", table_name="webhooks")
    op.drop_table("webhooks")
