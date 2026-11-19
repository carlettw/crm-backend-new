import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.v1 import (
    auth, boss, certificates, cron, currency, jobs, messages, superops, telegram, tours, training, users,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Role, User
from app.services import telegram as tg
from app.services import weekly

logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
log = logging.getLogger("app")

settings.check_production()  # xavfli standart sozlamalar bilan productionda ishga tushmaydi

if settings.sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, traces_sample_rate=0.0)
    except ImportError:  # pragma: no cover
        log.warning("SENTRY_DSN berilgan, lekin sentry-sdk o'rnatilmagan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:  # dev rejimi; productionda Alembic ishlatiladi
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        exists = (await db.execute(select(User).where(User.role == Role.super_admin))).first()
        if not exists:
            db.add(User(
                phone=settings.first_superadmin_phone,
                username=settings.first_superadmin_username,
                full_name="Super Admin",
                password_hash=hash_password(settings.first_superadmin_password),
                role=Role.super_admin,
                must_change_password=True,
            ))
            await db.commit()
    tasks = [asyncio.create_task(weekly.weekly_loop())]  # dushanba eslatmasi
    if tg.enabled():  # Telegram: webhook o'rnatish va xabarlar navbatini yuborish
        tasks += [asyncio.create_task(tg.setup()), asyncio.create_task(tg.sender_loop())]
    log.info("Server ishga tushdi (%s)", settings.environment)
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Turistik firma boshqaruv paneli", lifespan=lifespan)
for r in (auth.router, users.router, tours.router, jobs.router, boss.router, messages.router, superops.router,
          currency.router, telegram.router, training.router, certificates.router, cron.router):
    app.include_router(r, prefix="/api/v1")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Kutilmagan xato: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Serverda kutilmagan xato. Birozdan keyin qayta urinib ko'ring"})


app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    # lokal sinov uchun istalgan port (localhost / 127.0.0.1) faqat development rejimida ruxsat etiladi
    allow_origin_regex=None if settings.is_production else r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
