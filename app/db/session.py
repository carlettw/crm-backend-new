from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings


def make_engine(url: str | None = None):
    url = url or settings.database_url
    args = {}
    if url.startswith("postgresql"):
        # Supabase pooler (pgbouncer) bilan mos ishlashi uchun prepared statement keshi o'chiriladi
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0
        if settings.db_ssl:
            args["ssl"] = "require"
    kw = {}
    if url.startswith("postgresql"):
        # pre_ping har so'rovga qo'shimcha bazaga borib-kelish qo'shadi; o'rniga eski ulanishlar yangilanadi
        kw = dict(pool_size=5, max_overflow=5, pool_recycle=300)
    return create_async_engine(url, connect_args=args, **kw)


engine = make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with SessionLocal() as session:
        yield session
