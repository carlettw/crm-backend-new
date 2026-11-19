import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = ROOT / "test.db"
os.environ.update(DATABASE_URL=os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{DB}",
                  DB_SSL="false", AUTO_CREATE_TABLES="true", ENVIRONMENT="development",
                  SECRET_KEY="test-secret-key-0123456789-abcdefghijkl", TELEGRAM_BOT_TOKEN="",
                  FIRST_SUPERADMIN_PASSWORD="Super12345")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core.security import hash_password, ip_limiter, user_limiter  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402

PW = "Parol1234"


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        db.add(User(phone="+998900000000", username="superadmin", full_name="Super Admin",
                    password_hash=hash_password(PW), role=Role.super_admin))
        await db.commit()
    user_limiter.fails.clear()
    ip_limiter.fails.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1") as c:
        yield c
    await engine.dispose()


class Api:
    def __init__(self, c, token):
        self.c, self.h = c, {"Authorization": f"Bearer {token}"}

    async def req(self, method, url, expect=None, **kw):
        r = await self.c.request(method, url, headers=self.h, **kw)
        if expect is not None:
            assert r.status_code == expect, (r.status_code, r.text)
        return r

    async def get(self, url, expect=200, **kw):
        return (await self.req("GET", url, expect, **kw)).json()

    async def post(self, url, json=None, expect=200, **kw):
        r = await self.req("POST", url, expect, json=json, **kw)
        return r.json() if r.content else None

    async def put(self, url, json=None, expect=200):
        return (await self.req("PUT", url, expect, json=json)).json()

    async def patch(self, url, json=None, expect=200):
        return (await self.req("PATCH", url, expect, json=json)).json()


async def login(c, username, password=PW) -> Api:
    r = await c.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return Api(c, r.json()["access_token"])


@pytest.fixture
def anyio_backend():
    return "asyncio"
