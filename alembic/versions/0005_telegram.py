"""Telegram bildirishnomalari

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("telegram_linked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("tg_link_code", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("tg_link_expires", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"])
    op.create_index("ix_users_tg_link_code", "users", ["tg_link_code"])
    op.add_column("messages", sa.Column("tg_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("tg_tries", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("messages", "tg_tries")
    op.drop_column("messages", "tg_sent_at")
    op.drop_index("ix_users_tg_link_code", table_name="users")
    op.drop_index("ix_users_telegram_chat_id", table_name="users")
    op.drop_column("users", "tg_link_expires")
    op.drop_column("users", "tg_link_code")
    op.drop_column("users", "telegram_linked_at")
    op.drop_column("users", "telegram_chat_id")
