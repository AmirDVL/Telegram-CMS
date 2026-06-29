"""Surrogate id PK for PublishedDedupe + UNIQUE NULLS NOT DISTINCT constraint.

Replaces the broken composite PRIMARY KEY (tenant_id, dedupe_hash) design:
- PRIMARY KEY cannot include a nullable column (tenant_id is NULL in single-tenant
  mode), so we use a surrogate BigInteger id as the PK instead.
- Dedupe uniqueness is correctly enforced by a UNIQUE NULLS NOT DISTINCT constraint
  on (tenant_id, dedupe_hash), which is valid PG15+ syntax. This treats two NULL
  tenant_ids as equal, preserving global dedupe in single-tenant mode.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-29 00:00:00
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old single-column primary key on dedupe_hash.
    op.drop_constraint("published_dedupe_pkey", "published_dedupe", type_="primary")
    # Drop the standalone tenant_id index if it exists (the unique constraint below
    # provides a tenant_id-leading index, making it redundant).
    op.execute("DROP INDEX IF EXISTS ix_published_dedupe_tenant_id")

    # Surrogate primary key. A PRIMARY KEY cannot include the nullable tenant_id
    # column, so we add an identity id. Existing rows are backfilled automatically.
    op.add_column(
        "published_dedupe",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
    )
    op.create_primary_key("published_dedupe_pkey", "published_dedupe", ["id"])

    # Per-tenant dedupe scope. NULLS NOT DISTINCT (PG15+) makes single-tenant NULL
    # tenant_ids dedupe globally (two NULLs treated as equal). Valid on UNIQUE.
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
    op.drop_column("published_dedupe", "id")
    op.create_primary_key("published_dedupe_pkey", "published_dedupe", ["dedupe_hash"])
    op.create_index("ix_published_dedupe_tenant_id", "published_dedupe", ["tenant_id"])
