"""Gid viloyatlari, tur viloyati, to'lov kartasi

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guide_profiles", sa.Column("regions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("tours", sa.Column("region", sa.String(30), nullable=True))
    op.add_column("users", sa.Column("card_number", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("card_holder", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "card_holder")
    op.drop_column("users", "card_number")
    op.drop_column("tours", "region")
    op.drop_column("guide_profiles", "regions")
