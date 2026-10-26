"""Turda bir nechta til/turist guruhi, haydovchisiz turlar, admin tasdig'i

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tours", sa.Column("needs_driver", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "tour_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tour_id", sa.Integer(), sa.ForeignKey("tours.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("tourist_name", sa.String(120), nullable=False),
        sa.Column("tourist_phone", sa.String(30), nullable=True),
        sa.Column("tourist_email", sa.String(120), nullable=True),
        sa.Column("messenger", sa.String(120), nullable=True),
        sa.Column("pax_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tour_groups_tour_id", "tour_groups", ["tour_id"])
    # mavjud turlarning turist ma'lumotlari birinchi guruh sifatida ko'chiriladi
    op.execute(
        "INSERT INTO tour_groups (tour_id, position, language, tourist_name, tourist_phone, tourist_email, messenger, pax_count) "
        "SELECT id, 0, language, tourist_name, tourist_phone, tourist_email, messenger, pax_count FROM tours"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute('ALTER TABLE public."tour_groups" ENABLE ROW LEVEL SECURITY')  # Supabase Data API orqali ochiq qolmasin


def downgrade() -> None:
    op.drop_index("ix_tour_groups_tour_id", table_name="tour_groups")
    op.drop_table("tour_groups")
    op.drop_column("tours", "needs_driver")
