"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("filters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("original_title", sa.String(1024), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("original_url", sa.String(2048), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("raw_media", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("ai_processed_text", sa.JSON(), nullable=True),
        sa.Column("ai_category", sa.String(255), nullable=True),
        sa.Column("ai_tags", sa.JSON(), nullable=True),
        sa.Column("moderation_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_posts_hash", "posts", ["hash"])
    op.create_index("ix_posts_status", "posts", ["status"])

    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("file_path", sa.String(2048), nullable=True),
        sa.Column("file_type", sa.String(50), nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
    )

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.Integer(), nullable=True, unique=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
    )

    op.create_table(
        "logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("module", sa.String(255), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
    )
    op.create_index("ix_logs_timestamp", "logs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_logs_timestamp", table_name="logs")
    op.drop_table("logs")
    op.drop_table("settings")
    op.drop_table("admins")
    op.drop_table("media")
    op.drop_index("ix_posts_status", table_name="posts")
    op.drop_index("ix_posts_hash", table_name="posts")
    op.drop_table("posts")
    op.drop_table("sources")
