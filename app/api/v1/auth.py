from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import (
    create_access_token, create_refresh_token, decode_token, hash_password, ip_limiter, user_limiter,
    verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordIn, LoginIn, RefreshIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])

# username topilmaganda ham bcrypt ishlaydi — javob vaqti orqali username borligini bilib bo'lmasin
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _tokens(user: User) -> TokenOut:
    v = user.token_version or 0
    return TokenOut(access_token=create_access_token(user.id, v), refresh_token=create_refresh_token(user.id, v),
                    must_change_password=bool(user.must_change_password))


def _client_ip(request: Request) -> str:
    # Render proxy haqiqiy IP ni ro'yxat OXIRIGA qo'shadi; boshidagilarni mijoz o'zi yozib yuborishi mumkin
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "?"


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    ukey, ikey = "u:" + data.username, "ip:" + _client_ip(request)
    wait = max(user_limiter.retry_after(ukey), ip_limiter.retry_after(ikey))
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Juda ko'p noto'g'ri urinish. {max(1, wait // 60)} daqiqadan keyin qayta urinib ko'ring",
                            headers={"Retry-After": str(wait)})
    user = (await db.execute(select(User).where(User.username == data.username))).scalar_one_or_none()
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
        user_limiter.fail(ukey)
        ip_limiter.fail(ikey)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username yoki parol noto'g'ri")
    user_limiter.reset(ukey)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akkaunt faol emas")
    return _tokens(user)


@router.post("/refresh", response_model=TokenOut)
async def refresh(data: RefreshIn, db: AsyncSession = Depends(get_db)):
    dec = decode_token(data.refresh_token, "refresh")
    if dec is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token yaroqsiz")
    user_id, ver = dec
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Foydalanuvchi faol emas")
    if (user.token_version or 0) != ver:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessiya bekor qilingan, qayta kiring")
    return _tokens(user)


@router.post("/change-password", response_model=TokenOut)
async def change_password(
    data: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parol o'zgaradi va boshqa barcha qurilmalardagi sessiyalar bekor bo'ladi; joriy qurilma uchun yangi token qaytadi."""
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Eski parol noto'g'ri")
    if data.old_password == data.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Yangi parol eskisidan farq qilishi kerak")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    return _tokens(user)


@router.post("/logout-all", status_code=204)
async def logout_all(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Barcha qurilmalardagi sessiyalarni bekor qilish (shu qurilma ham)."""
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
