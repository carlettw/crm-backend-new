from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.timeutil import now
from app.db.session import get_db
from app.models import BossAdmin, Message, Role, User
from app.services.common import notify

router = APIRouter(prefix="/messages", tags=["xabarlar"])


class SendIn(BaseModel):
    username: str
    body: str = Field(min_length=1, max_length=4000)


class BroadcastIn(BaseModel):
    target: str = Field(pattern="^(guide|driver|admin|boss|all)$")
    body: str = Field(min_length=1, max_length=4000)
    min_guide_level: int | None = Field(None, ge=1, le=7)  # gidlar uchun ixtiyoriy filtr


async def _allowed(db, s: User, r: User) -> bool:
    if s.role == Role.super_admin or r.role == Role.super_admin:
        return True   # har kim super admin bilan bog'lana oladi
    pair = {s.role, r.role}
    if pair == {Role.boss, Role.admin}:
        boss, admin = (s, r) if s.role == Role.boss else (r, s)
        return await db.get(BossAdmin, (boss.id, admin.id)) is not None
    if Role.admin in pair and pair & {Role.guide, Role.driver}:
        return True
    return False


@router.post("", status_code=201)
async def send(data: SendIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(User).where(User.username == data.username.lower()))).scalar_one_or_none()
    if r is None or not r.is_active:
        raise HTTPException(404, "Bunday username topilmadi")
    if r.id == user.id or not await _allowed(db, user, r):
        raise HTTPException(403, "Bu foydalanuvchiga xabar yubora olmaysiz")
    await notify(db, [r.id], data.body, user.id)
    await db.commit()
    return {"ok": True}


@router.post("/broadcast")
async def broadcast(data: BroadcastIn, user: User = Depends(require_roles(Role.super_admin)),
                    db: AsyncSession = Depends(get_db)):
    """Super admin: gidlarga / haydovchilarga / hammaga ommaviy xabar (masalan suhbat vaqti va joyi)."""
    q = select(User).where(User.is_active.is_(True), User.id != user.id)
    if data.target != "all":
        q = q.where(User.role == Role(data.target))
    users = (await db.execute(q)).scalars().all()
    if data.min_guide_level:
        users = [u for u in users if u.role != Role.guide or u.guide_profile.level >= data.min_guide_level]
    await notify(db, [u.id for u in users], data.body, user.id)
    await db.commit()
    return {"sent": len(users)}


def _out(m: Message):
    return dict(id=m.id, sender_id=m.sender_id, sender_name=m.sender_name, body=m.body,
                created_at=m.created_at, read=m.read_at is not None)


@router.get("")
async def inbox(unread_only: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = 0,
                user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    q = select(Message).where(Message.recipient_id == user.id)
    if unread_only:
        q = q.where(Message.read_at.is_(None))
    rows = (await db.execute(q.order_by(Message.id.desc()).limit(limit).offset(offset))).scalars().all()
    unread = (await db.execute(select(func.count()).where(
        Message.recipient_id == user.id, Message.read_at.is_(None)))).scalar_one()
    return {"unread": unread, "items": [_out(m) for m in rows]}


@router.post("/{message_id}/read", status_code=204)
async def mark_read(message_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    m = await db.get(Message, message_id)
    if m is None or m.recipient_id != user.id:
        raise HTTPException(404, "Xabar topilmadi")
    m.read_at = m.read_at or now()
    await db.commit()
