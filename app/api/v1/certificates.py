"""Sertifikatlar: gidga berish va OCHIQ tekshirish (kod yoki QR orqali)."""
import io

import segno
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_roles
from app.core.timeutil import now
from app.db.session import get_db
from app.models import Certificate, Role, User

def _enabled():
    if not settings.certificates_enabled:
        raise HTTPException(404, "Sertifikatlash hozircha o'chirilgan")


router = APIRouter(tags=["sertifikat"], dependencies=[Depends(_enabled)])


def _out(c: Certificate, public: bool = False) -> dict:
    d = dict(code=c.code, holder=c.holder_name, issued_at=c.issued_at, tours=c.tours or [],
             revoked=c.revoked, revoked_reason=c.revoked_reason if c.revoked else None)
    if public:
        d["valid"] = not c.revoked
        d["title"] = "Gid amaliyoti sertifikati"
    return d


async def _by_code(db, code: str) -> Certificate:
    c = (await db.execute(select(Certificate).where(Certificate.code == code.strip().upper()))).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "Bunday sertifikat topilmadi")
    return c


@router.get("/certificates/verify/{code}")
async def verify(code: str, db: AsyncSession = Depends(get_db)):
    """OCHIQ endpoint (login shart emas): sertifikat haqiqiyligini tekshirish."""
    return _out(await _by_code(db, code), public=True)


@router.get("/certificates/{code}/qr.svg")
async def qr(code: str, base: str | None = Query(None, description="Frontend manzili (FRONTEND_URL berilmagan bo'lsa)"),
             db: AsyncSession = Depends(get_db)):
    """Sertifikatdagi QR: tekshirish sahifasiga havola."""
    c = await _by_code(db, code)
    root = (settings.frontend_url or base or "").rstrip("/")
    if not root.startswith(("http://", "https://")):
        raise HTTPException(400, "Frontend manzili ko'rsatilmagan")
    buf = io.BytesIO()
    segno.make(f"{root}/?verify={c.code}", error="m").save(buf, kind="svg", scale=8, border=1, dark="#0f1626")
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/me/certificate")
async def my_certificate(user: User = Depends(require_roles(Role.guide)), db: AsyncSession = Depends(get_db)):
    c = (await db.execute(select(Certificate).where(Certificate.user_id == user.id))).scalar_one_or_none()
    return _out(c, public=True) if c else None


@router.get("/certificates")
async def list_certificates(_: User = Depends(require_roles(Role.super_admin)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Certificate).order_by(Certificate.id.desc()))).scalars().all()
    return [dict(_out(c), id=c.id) for c in rows]


class RevokeIn(BaseModel):
    reason: str = ""


@router.post("/certificates/{cert_id}/revoke")
async def revoke(cert_id: int, data: RevokeIn, _: User = Depends(require_roles(Role.super_admin)), db: AsyncSession = Depends(get_db)):
    c = await db.get(Certificate, cert_id)
    if c is None:
        raise HTTPException(404, "Sertifikat topilmadi")
    c.revoked, c.revoked_reason, c.revoked_at = True, (data.reason or "Bekor qilingan")[:200], now()
    await db.commit()
    return _out(c, public=True)
