"""Sertifikatlar va tur izohlari

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "certificates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("holder_name", sa.String(120), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tours", sa.JSON(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("revoked_reason", sa.String(200), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_certificates_code", "certificates", ["code"], unique=True)
    op.create_table(
        "tour_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tour_id", sa.Integer(), sa.ForeignKey("tours.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tour_comments_tour_id", "tour_comments", ["tour_id"])
    op.create_index("ix_tour_comments_user_id", "tour_comments", ["user_id"])
    if op.get_bind().dialect.name == "postgresql":  # Supabase Data API orqali ochiq qolmasin
        op.execute('ALTER TABLE public."certificates" ENABLE ROW LEVEL SECURITY')
        op.execute('ALTER TABLE public."tour_comments" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    op.drop_table("tour_comments")
    op.drop_table("certificates")
