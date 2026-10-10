"""Gidlar tillari va tur tili

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guide_profiles", sa.Column("languages", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("tours", sa.Column("language", sa.String(5), nullable=False, server_default="uz"))


def downgrade() -> None:
    op.drop_column("tours", "language")
    op.drop_column("guide_profiles", "languages")
