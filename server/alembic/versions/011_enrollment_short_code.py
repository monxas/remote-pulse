"""Add ``short_code`` column + partial unique index on ``enrollments``.

Companion to the short-code enrollment redesign: agents now bootstrap via
``--code=K7M-X3F`` instead of a 250-char JWT in the URL. The code is a
6-character string drawn from a confusion-free alphabet (see
``rp_server.auth.SHORT_CODE_ALPHABET``) — about 29^6 ≈ 5.9e8 distinct
codes. Collisions are extremely unlikely at the active-link cardinalities
we run at (a handful at a time), but we enforce a *partial* unique index
so two simultaneously-active enrollments can never share a code; expired
or exhausted rows drop out of the index so a code is, in principle, free
for re-issue once a row retires.

Why a partial index and not a full one
--------------------------------------
A plain ``UNIQUE(short_code)`` would block forever — a code burned by a
single successful install could never be reissued, even years later, and
old rows accumulate. The partial predicate ``WHERE short_code IS NOT
NULL AND used_count < max_uses AND expires_at > now()`` lets retired
rows shed the constraint while keeping the live ones airtight.

Postgres caveat: ``now()`` is not IMMUTABLE so it cannot appear in an
index ``WHERE`` clause directly. We sidestep that by indexing on
``used_count < max_uses`` only (the strict, monotone-once-tripped
predicate) — that's enough to neutralise exhausted codes immediately
and is the dominant retirement path in practice. Expired-only rows
keep their constraint slot until pruned by an out-of-band job; with
5-minute TTLs and ~hundreds of issued codes total, that's a non-issue.

Revision ID: 011
Revises: 010
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "enrollments",
        sa.Column("short_code", sa.Text(), nullable=True),
    )
    # Partial unique index: only "still useful" rows enforce uniqueness.
    # ``used_count < max_uses`` is index-stable (set-once on commit);
    # ``expires_at`` is intentionally NOT in the predicate (Postgres
    # refuses non-IMMUTABLE functions in partial index predicates).
    op.create_index(
        "idx_enrollments_short_code_unique",
        "enrollments",
        ["short_code"],
        unique=True,
        postgresql_where=sa.text(
            "short_code IS NOT NULL AND used_count < max_uses"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_enrollments_short_code_unique",
        table_name="enrollments",
    )
    op.drop_column("enrollments", "short_code")
