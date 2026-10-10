from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.security import hash_password
from app.db.session import get_db
from app.models.user import BossProfile, DriverProfile, GuideProfile, LevelRate, Role, User
from app.schemas.user import (
    ActiveIn, LangsIn, LevelRateIn, LevelRateOut, ResetPasswordIn, UserCreate, UserListOut, UserOut,
)

router = APIRouter(tags=["users"])
super_only = require_roles(Role.super_admin)


@router.get("/languages")
async def languages(_: User = Depends(get_current_user)):
    from app.core.languages import LANGUAGES
    return [{"code": k, "name": v} for k, v in LANGUAGES.items()]


@router.put("/me/languages", response_model=UserOut)
async def set_my_languages(data: LangsIn, user: User = Depends(require_roles(Role.guide)), db: AsyncSession = Depends(get_db)):
    """Gid o'zi biladigan tillarni yangilaydi."""
    user.guide_profile.languages = data.languages
    await db.commit()
    return user


@router.get("/users/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(data: UserCreate, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    user = User(
        phone=data.phone,
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    if data.role == Role.boss:
        user.boss_profile = BossProfile(super_admin_percent=data.boss_percent)
    elif data.role == Role.guide:
        user.guide_profile = GuideProfile(level=data.guide_level, languages=data.languages)
    elif data.role == Role.driver:
        user.driver_profile = DriverProfile(car_model=data.car_model)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Bu username band (telefon raqam esa takrorlanishi mumkin)")
    await db.refresh(user)
    return user


@router.get("/users", response_model=UserListOut)
async def list_users(
    search: str | None = Query(None, description="Ism, telefon yoki username bo'yicha"),
    role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(super_only),
    db: AsyncSession = Depends(get_db),
):
    q = select(User)
    if role:
        try:
            q = q.where(User.role == Role(role))
        except ValueError:
            raise HTTPException(400, "Noma'lum rol")
    if search:
        like = f"%{search}%"
        q = q.where(or_(User.full_name.ilike(like), User.phone.ilike(like), User.username.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    items = (await db.execute(q.order_by(User.id.desc()).limit(limit).offset(offset))).scalars().all()
    return UserListOut(total=total, items=items)


async def _get_or_404(db: AsyncSession, user_id: int) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(404, "Foydalanuvchi topilmadi")
    return user


@router.patch("/users/{user_id}/active", response_model=UserOut)
async def set_active(user_id: int, data: ActiveIn, me: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    user = await _get_or_404(db, user_id)
    if user.id == me.id:
        raise HTTPException(400, "O'zingizni o'chira olmaysiz")
    user.is_active = data.is_active
    await db.commit()
    return user


@router.post("/users/{user_id}/reset-password", status_code=204)
async def reset_password(user_id: int, data: ResetPasswordIn, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    user = await _get_or_404(db, user_id)
    user.password_hash = hash_password(data.new_password)
    await db.commit()


# ---- Daraja summalari (faqat 3-7 daraja to'lanadi) ----
@router.get("/level-rates")
async def get_rates(_: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """3-7 darajalar: amount — o'zi uchun belgilangan, effective — amaldagi eng kam summa
    (pastki darajalardan meros bo'lib o'tadi)."""
    own = {r.level: r.amount for r in (await db.execute(select(LevelRate))).scalars().all()}
    out, top = [], None
    for lvl in range(3, 8):  # amaldagi summa: o'zi va pastki darajalarning eng kattasi
        if own.get(lvl) is not None:
            top = max(top or 0, own[lvl])
        out.append({"level": lvl, "amount": own.get(lvl), "effective": top})
    return out


@router.put("/level-rates/{level}", response_model=LevelRateOut)
async def set_rate(level: int, data: LevelRateIn, _: User = Depends(super_only), db: AsyncSession = Depends(get_db)):
    if not 3 <= level <= 7:
        raise HTTPException(400, "Summa faqat 3-7 darajalar uchun belgilanadi (1-2 daraja bepul)")
    rate = await db.get(LevelRate, level)
    if rate is None:
        rate = LevelRate(level=level, amount=data.amount)
        db.add(rate)
    else:
        rate.amount = data.amount
    await db.commit()
    return rate
