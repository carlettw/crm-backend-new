import asyncio

from alembic import context

from app.core.config import settings
from app.db.base import Base
from app.db.session import make_engine
import app.models  # noqa: F401

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _online():
    engine = make_engine()
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_online())
