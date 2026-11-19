from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.core.timeutil import period_range, today_local
from app.db.session import get_db
from app.models import AppSetting, BossProfile, GuideProfile, Role, Tour, TourStatus, User
from app.services.common import SETTING_DEFAULTS, level_up_check, notify

router = APIRouter(tags=["super admin"])
super_only = require_roles(Role.super_admin)


class LangsBody(BaseModel):
    languages: list[str] = Field(min_length=1)


class RegionsBody(BaseModel):
    regions: list[str] = Field(min_length=1)


class LevelIn(BaseModel):
    level: int = Field(ge=1, le=7)


class SettingIn(BaseModel):
    value: str


async def _guide(db, user_id) -> GuideProfile:
    gp = (await db.execute(select(GuideProfile).where(GuideProfile.user_id == user_id))).scalar_one_or_none()
    if gp is None:
        raise HTTPException(404, "Gid topilmadi")
    return gp


@router.patch("/guides/{user_id}/level")
async def set_level(user_id: int, data: LevelIn, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    """4-darajadan yuqori ko'tarish (va istalgan tuzatish) qo'lda."""
    gp = await _guide(db, user_id)
    gp.level, gp.level_tours = data.level, 0
    await notify(db, [user_id], f"Darajangiz {data.level}-darajaga o'zgartirildi.")
    await db.commit()
    return {"level": gp.level}


@router.put("/guides/{user_id}/languages")
async def set_guide_languages(user_id: int, data: LangsBody, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    from app.core.languages import clean_languages
    gp = await _guide(db, user_id)
    try:
        gp.languages = clean_languages(data.languages)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return {"languages": gp.languages}


@router.put("/guides/{user_id}/regions")
async def set_guide_regions(user_id: int, data: RegionsBody, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    from app.core.regions import clean_regions
    gp = await _guide(db, user_id)
    try:
        gp.regions = clean_regions(data.regions)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await db.commit()
    return {"regions": gp.regions}


@router.get("/settings")
async def get_settings(_: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    rows = {r.key: r.value for r in (await db.execute(select(AppSetting))).scalars().all()}
    return {k: rows.get(k, v) for k, v in SETTING_DEFAULTS.items()}


@router.put("/settings/{key}")
async def put_setting(key: str, data: SettingIn, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    """admin_fee_usd — admin haqi, har tur uchun $. Dollar kursi: PUT /currency/rate."""
    if key not in SETTING_DEFAULTS:
        raise HTTPException(404, "Noma'lum sozlama")
    try:
        float(data.value)
    except ValueError:
        raise HTTPException(400, "Qiymat son bo'lishi kerak")
    row = await db.get(AppSetting, key)
    if row:
        row.value = data.value
    else:
        db.add(AppSetting(key=key, value=data.value))
    await db.commit()
    return {key: data.value}


@router.get("/super/share")
async def my_share(month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
                   _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    """Super admin faqat o'z ulushini ko'radi: har boshliq oylik foydasidan belgilangan foiz.
    Boshliqlarning aylanma/foyda summalari KO'RSATILMAYDI."""
    from datetime import date
    today = today_local()  # Toshkent sanasi (server UTC'da ishlaydi)
    y, m = (int(month[:4]), int(month[5:])) if month else (today.year, today.month)
    if not 1 <= m <= 12:
        raise HTTPException(400, "Oy noto'g'ri")
    start, end = period_range("month", date(y, m, 1))
    bosses = (await db.execute(select(User, BossProfile).join(BossProfile, BossProfile.user_id == User.id)
                               .where(User.role == Role.boss))).all()
    # ulush tur YAKUNLANGAN oy bo'yicha hisoblanadi (bitta so'rovda)
    profits = dict((await db.execute(select(Tour.boss_id, func.coalesce(func.sum(Tour.profit), 0)).where(
        Tour.status == TourStatus.completed, Tour.completed_at >= start, Tour.completed_at < end)
        .group_by(Tour.boss_id))).all())
    items, total = [], 0
    for u, bp in bosses:
        profit = profits.get(u.id, 0)
        share = int(round(max(profit, 0) * bp.super_admin_percent / 100))
        items.append(dict(boss_id=u.id, boss_name=u.full_name, percent=bp.super_admin_percent, share=share))
        total += share
    return {"month": f"{y}-{m:02d}", "items": items, "total": total}
