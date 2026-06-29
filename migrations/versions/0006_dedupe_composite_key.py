"""Composite primary key for PublishedDedupe (tenant_id, dedupe_hash).

Fixes per-tenant dedupe correctness: with a single-column PK on dedupe_hash,
tenant A publishing content X blocks tenant B from publishing identical content.
The composite PK (tenant_id, dedupe_hash) with NULLS NOT DISTINCT ensures:
- Multi-tenant mode: each tenant has independent dedupe scope.
- Single-tenant mode (tenant_id=NULL): two NULLs are treated as equal, preserving
  the original global dedupe behavior.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-29 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old single-column PK and the now-redundant tenant_id index.
    op.drop_constraint("published_dedupe_pkey", "published_dedupe", type_="primary")
    op.drop_index("ix_published_dedupe_tenant_id", "published_dedupe")

    # Add composite PK (tenant_id, dedupe_hash) with NULLS NOT DISTINCT.
    # SQLAlchemy/Alembic doesn't expose this option via create_primary_key(),
    # so we use raw SQL. Postgres 15+ feature.
    op.execute(
        """
        ALTER TABLE published_dedupe
        ADD CONSTRAINT published_dedupe_pkey
        PRIMARY KEY (tenant_id, dedupe_hash) NULLS NOT DISTINCT
        """
    )

    # Also add a unique constraint with NULLS NOT DISTINCT for completeness
    # (the PK already enforces uniqueness, but this makes conflict resolution clearer).
    op.execute(
        """
        ALTER TABLE published_dedupe
        ADD CONSTRAINT uq_published_dedupe_tenant_hash
        UNIQUE NULLS NOT DISTINCT (tenant_id, dedupe_hash)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE published_dedupe DROP CONSTRAINT uq_published_dedupe_tenant_hash")
    op.drop_constraint("published_dedupe_pkey", "published_dedupe", type_="primary")
    op.execute("ALTER TABLE published_dedupe ADD CONSTRAINT published_dedupe_pkey PRIMARY KEY (dedupe_hash)")
    op.create_index("ix_published_dedupe_tenant_id", "published_dedupe", ["tenant_id"])
