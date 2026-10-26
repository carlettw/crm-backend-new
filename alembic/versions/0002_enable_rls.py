"""Supabase: barcha jadvallarda RLS yoqiladi (Data API orqali ochiq qolmasligi uchun)

Backend `postgres` roli bilan ulanadi (RLS'ni chetlab o'tadi), anon/authenticated esa hech narsa ko'rmaydi.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _tables(bind):
    return sa.inspect(bind).get_table_names(schema="public")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for t in _tables(bind):
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for t in _tables(bind):
        op.execute(f'ALTER TABLE public."{t}" DISABLE ROW LEVEL SECURITY')
