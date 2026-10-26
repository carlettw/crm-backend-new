from dataclasses import dataclass

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import BossAdmin, Role, Tour, User


@dataclass
class Ctx:
    user: User
    boss_id: int


async def _resolve(user: User, boss_id: int | None, db: AsyncSession, roles: tuple[Role, ...]) -> Ctx:
    if user.role not in roles:
        raise HTTPException(403, "Bu amal uchun ruxsat yo'q")
    if user.role == Role.boss:
        return Ctx(user, user.id)
    if boss_id is None:
        raise HTTPException(400, "Qaysi boshliq ishi ekanini boss_id bilan ko'rsating")
    if await db.get(BossAdmin, (boss_id, user.id)) is None:
        raise HTTPException(403, "Siz bu boshliqqa biriktirilmagansiz")
    return Ctx(user, boss_id)


async def read_ctx(boss_id: int | None = Query(None), user: User = Depends(get_current_user),
                   db: AsyncSession = Depends(get_db)) -> Ctx:
    return await _resolve(user, boss_id, db, (Role.boss, Role.admin))


async def admin_ctx(boss_id: int | None = Query(None), user: User = Depends(get_current_user),
                    db: AsyncSession = Depends(get_db)) -> Ctx:
    return await _resolve(user, boss_id, db, (Role.admin,))


async def get_tour_or_404(db: AsyncSession, tour_id: int, boss_id: int | None = None) -> Tour:
    t = await db.get(Tour, tour_id)
    if t is None or (boss_id is not None and t.boss_id != boss_id):
        raise HTTPException(404, "Tur topilmadi")
    return t
