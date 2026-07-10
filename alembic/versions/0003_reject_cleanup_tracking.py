"""rejected_at + scheduled_by tracking

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("scheduled_by", sa.String(255), nullable=True))
    op.add_column("posts", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    # Backfill so posts rejected before this migration are still eligible for the
    # new 7-day retention cleanup, instead of being stuck forever with a NULL rejected_at.
    op.execute("UPDATE posts SET rejected_at = created_at WHERE status = 'rejected' AND rejected_at IS NULL")


def downgrade() -> None:
    op.drop_column("posts", "rejected_at")
    op.drop_column("posts", "scheduled_by")
