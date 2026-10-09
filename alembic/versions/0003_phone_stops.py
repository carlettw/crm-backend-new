"""Telefon takrorlanishi mumkin; nuqtalarga lokatsiya va vaqt

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"], unique=False)
    op.add_column("tour_stops", sa.Column("location_url", sa.String(500), nullable=True))
    op.add_column("tour_stops", sa.Column("arrival_time", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("tour_stops", "arrival_time")
    op.drop_column("tour_stops", "location_url")
    op.drop_index("ix_users_phone", table_name="users")
    op.create_index("ix_users_phone", "users", ["phone"], unique=True)
