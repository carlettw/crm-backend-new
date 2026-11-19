"""Amaliyotchilarni turga biriktirish (admin) va tur izohlari."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ctx import Ctx, admin_ctx, get_tour_or_404, read_ctx
from app.core.deps import require_roles
from app.db.session import get_db
from app.models import AppKind, AppStatus, GuideProfile, Role, TourApplication, TourComment, TourStatus, User
from app.schemas.tour import CommentIn, TraineesIn
from app.services.certificates import practice_counts
from app.services.common import fmt_dt, notify

router = APIRouter(tags=["amaliyot va izohlar"])


@router.get("/trainees")
async def list_trainees(_: User = Depends(require_roles(Role.admin, Role.boss)), db: AsyncSession = Depends(get_db)):
    """1-daraja (amaliyotchi) gidlar: admin ularni turga biriktiradi."""
    users = (await db.execute(
        select(User).join(GuideProfile, GuideProfile.user_id == User.id).where(
            User.role == Role.guide, User.is_active.is_(True), GuideProfile.level == 1).order_by(User.full_name)
    )).scalars().all()
    counts = await practice_counts(db, [u.id for u in users])
    return [dict(id=u.id, full_name=u.full_name, phone=u.phone, regions=u.regions, languages=u.languages,
                 practice_types=counts[u.id]["types"], practice_tours=counts[u.id]["all_tours"]) for u in users]


async def _assigned(db, tour_id: int):
    return (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == tour_id, TourApplication.kind == AppKind.practice,
        TourApplication.status == AppStatus.approved).order_by(TourApplication.id))).scalars().all()


@router.get("/tours/{tour_id}/trainees")
async def tour_trainees(tour_id: int, ctx: Ctx = Depends(read_ctx), db: AsyncSession = Depends(get_db)):
    await get_tour_or_404(db, tour_id, ctx.boss_id)
    return [dict(id=a.user_id, full_name=a.user.full_name, phone=a.user.phone) for a in await _assigned(db, tour_id)]


@router.put("/tours/{tour_id}/trainees")
async def set_trainees(tour_id: int, data: TraineesIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Turga biriktiriladigan amaliyotchilar ro'yxati (istalgancha: masalan 3 ta). Ro'yxatdan chiqarilganlar olib tashlanadi."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status not in (TourStatus.draft, TourStatus.open, TourStatus.ready):
        raise HTTPException(400, "Amaliyotchini faqat yakunlanmagan turga biriktirish mumkin")
    ids = set(data.user_ids)
    if ids:
        ok = set((await db.execute(select(User.id).join(GuideProfile, GuideProfile.user_id == User.id).where(
            User.id.in_(ids), User.role == Role.guide, User.is_active.is_(True), GuideProfile.level == 1))).scalars().all())
        if ids - ok:
            raise HTTPException(400, "Faqat faol 1-daraja (amaliyotchi) gidlarni biriktirish mumkin")
    existing = {a.user_id: a for a in (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == t.id, TourApplication.kind == AppKind.practice))).scalars().all()}
    for uid in ids:
        a = existing.get(uid)
        if a is None:
            db.add(TourApplication(tour_id=t.id, user_id=uid, kind=AppKind.practice, status=AppStatus.approved))
        elif a.status != AppStatus.approved:
            a.status = AppStatus.approved
        else:
            continue
        await notify(db, [uid], f"Sizni amaliyotga biriktirdilar: «{t.title}» — {fmt_dt(t.start_at)}. "
                                f"Manzil: {t.pickup_address or '—'}. Ma'lumotlar «Turlarim» bo'limida.", ctx.user.id)
    for uid, a in existing.items():
        if uid not in ids and a.status == AppStatus.approved:
            a.status = AppStatus.withdrawn
            await notify(db, [uid], f"«{t.title}» turidagi amaliyotdan chiqarildingiz.", ctx.user.id)
    await db.commit()
    return [dict(id=a.user_id, full_name=a.user.full_name, phone=a.user.phone) for a in await _assigned(db, t.id)]


def _c(c: TourComment):
    return dict(id=c.id, user_id=c.user_id, author=c.user.full_name, role=c.role, body=c.body, created_at=c.created_at)


@router.get("/tours/{tour_id}/comments")
async def tour_comments(tour_id: int, ctx: Ctx = Depends(read_ctx), db: AsyncSession = Depends(get_db)):
    """Admin va boshliq turdagi barcha izohlarni ko'radi."""
    await get_tour_or_404(db, tour_id, ctx.boss_id)
    rows = (await db.execute(select(TourComment).where(TourComment.tour_id == tour_id).order_by(TourComment.id))).scalars().all()
    return [_c(c) for c in rows]


@router.post("/tours/{tour_id}/comments", status_code=201)
async def admin_comment(tour_id: int, data: CommentIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status == TourStatus.draft:
        raise HTTPException(400, "Shablonga izoh yozib bo'lmaydi")
    c = TourComment(tour_id=t.id, user_id=ctx.user.id, role="admin", body=data.body.strip())
    db.add(c)
    await db.commit()
    return {"id": c.id}
