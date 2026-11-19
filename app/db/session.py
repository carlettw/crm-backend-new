from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings


def make_engine(url: str | None = None):
    url = url or settings.database_url
    args = {}
    if url.startswith("postgresql"):
        # Prepared statement keshi: har so'rovda bazaga bitta borib-kelishni tejaydi.
        # Supabase "session" pooler (port 5432) va oddiy Postgres bilan ishlaydi; "transaction" pooler (6543) bilan — yo'q.
        if not settings.db_statement_cache or ":6543/" in url:
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


async def try_lock(db, key: int) -> bool:
    """Postgres: tranzaksiya davomidagi advisory lock (bir nechta server nusxasi bir ishni ikki marta qilmasin).
    SQLite'da har doim True."""
    if db.bind.dialect.name != "postgresql":
        return True
    from sqlalchemy import text
    return bool((await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key})).scalar())
