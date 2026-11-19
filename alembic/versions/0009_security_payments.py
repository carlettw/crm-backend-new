"""Xavfsizlik: token versiyasi, parolni almashtirish majburiyati, shifrlangan karta; to'lov e'tirozi; indekslar

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("users") as b:
        b.alter_column("card_number", type_=sa.String(255), existing_type=sa.String(16), existing_nullable=True)

    # mavjud karta raqamlarini shifrlash
    from app.core.security import encrypt_str
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, card_number FROM users WHERE card_number IS NOT NULL")).all()
    for uid, num in rows:
        if num and num.isdigit():
            bind.execute(sa.text("UPDATE users SET card_number = :c WHERE id = :i"), {"c": encrypt_str(num), "i": uid})

    op.add_column("payments", sa.Column("dispute_reason", sa.Text(), nullable=True))
    op.create_index("ix_messages_recipient_unread", "messages", ["recipient_id", "read_at"])
    op.create_index("ix_messages_tg_pending", "messages", ["tg_sent_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_messages_tg_pending", table_name="messages")
    op.drop_index("ix_messages_recipient_unread", table_name="messages")
    op.drop_column("payments", "dispute_reason")
    from app.core.security import decrypt_str
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, card_number FROM users WHERE card_number IS NOT NULL")).all()
    for uid, num in rows:
        bind.execute(sa.text("UPDATE users SET card_number = :c WHERE id = :i"), {"c": decrypt_str(num), "i": uid})
    with op.batch_alter_table("users") as b:
        b.alter_column("card_number", type_=sa.String(16), existing_type=sa.String(255), existing_nullable=True)
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "token_version")
