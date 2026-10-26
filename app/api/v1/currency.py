from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Role, UsdRateLog, User
from app.services.common import DEFAULT_USD_RATE, get_usd_rate

router = APIRouter(prefix="/currency", tags=["valyuta"])


class RateIn(BaseModel):
    rate: float = Field(gt=0, description="1 dollar necha so'm")


@router.get("/rate")
async def current_rate(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(UsdRateLog).order_by(UsdRateLog.id.desc()).limit(1))).scalar_one_or_none()
    return {"rate": await get_usd_rate(db), "is_default": row is None, "updated_at": row.created_at if row else None}


@router.put("/rate", status_code=201)
async def set_rate(data: RateIn, user: User = Depends(require_roles(Role.super_admin)), db: AsyncSession = Depends(get_db)):
    """Super admin dollar kursini istalgan vaqtda kiritadi. Yangi kurs keyingi hisoblarga ta'sir qiladi:
    yangi/yangilangan turlar va yakunlanayotgan dollarli turlar."""
    db.add(UsdRateLog(rate=data.rate, set_by=user.id))
    await db.commit()
    return {"rate": data.rate}


@router.get("/rate/history")
async def history(limit: int = 50, _: User = Depends(require_roles(Role.super_admin)), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(UsdRateLog).order_by(UsdRateLog.id.desc()).limit(limit))).scalars().all()
    return [{"rate": r.rate, "set_by": r.set_by, "created_at": r.created_at} for r in rows]
