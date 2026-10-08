from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.security import (
    create_access_token, create_refresh_token, decode_token, hash_password, verify_password,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import ChangePasswordIn, LoginIn, RefreshIn, TokenOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user_id: int) -> TokenOut:
    return TokenOut(access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id))


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == data.username))).scalar_one_or_none()
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Username yoki parol noto'g'ri")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akkaunt faol emas")
    return _tokens(user.id)


@router.post("/refresh", response_model=TokenOut)
async def refresh(data: RefreshIn, db: AsyncSession = Depends(get_db)):
    user_id = decode_token(data.refresh_token, "refresh")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token yaroqsiz")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Foydalanuvchi faol emas")
    return _tokens(user.id)


@router.post("/change-password", status_code=204)
async def change_password(
    data: ChangePasswordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Eski parol noto'g'ri")
    user.password_hash = hash_password(data.new_password)
    await db.commit()
