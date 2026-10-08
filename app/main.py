from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import select

from app.api.v1 import auth, boss, currency, jobs, messages, superops, tours, users
from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.models import Role, User


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
            ))
            await db.commit()
    yield


app = FastAPI(title="Turistik firma boshqaruv paneli", lifespan=lifespan)
app.include_router(auth.router, prefix="/api/v1")
for r in (users.router, tours.router, jobs.router, boss.router, messages.router, superops.router, currency.router):
    app.include_router(r, prefix="/api/v1")

app.add_middleware(GZipMiddleware, minimum_size=800)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
