from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.timeutil import aware, local_day_range, now, today_local
from app.db.session import get_db
from app.models import (
    AppKind, AppStatus, GuideProfile, Rating, Role, Tour, TourApplication, TourCancellation,
    TourStatus, User,
)
from app.schemas.tour import LateIn, RateIn, ReasonIn
from app.services.common import (
    driver_rating, finalize_tour, hours_left_ok, notify, recompute_status,
)
from app.services.tourview import job_view

router = APIRouter(prefix="/jobs", tags=["ishlar (gid/haydovchi)"])
guide_only = require_roles(Role.guide)
driver_only = require_roles(Role.driver)
worker = require_roles(Role.guide, Role.driver)


async def _tour(db, tour_id) -> Tour:
    t = await db.get(Tour, tour_id)
    if t is None or t.status == TourStatus.draft:
        raise HTTPException(404, "Tur topilmadi")
    return t


# ---------------- GID ----------------
@router.get("/guide/available")
async def guide_available(user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    """2+ daraja: o'z darajasiga mos, hali gid olmagan turlar."""
    lvl = user.guide_profile.level
    if lvl < 2:
        return []
    q = select(Tour).where(Tour.status == TourStatus.open, Tour.guide_id.is_(None),
                           Tour.min_guide_level <= lvl, Tour.start_at > now()).order_by(Tour.start_at)
    return [job_view(t, "guide", lvl) for t in (await db.execute(q)).scalars().all()]


@router.get("/guide/practice-available")
async def practice_available(user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    """1-daraja: yaqin 48 soat ichidagi turlar (yordamchi sifatida ariza berish uchun)."""
    if user.guide_profile.level != 1:
        return []
    q = select(Tour).where(Tour.status.in_([TourStatus.open, TourStatus.ready]),
                           Tour.start_at > now(), Tour.start_at < now() + timedelta(hours=48)).order_by(Tour.start_at)
    return [job_view(t, "guide", 1) for t in (await db.execute(q)).scalars().all()]


@router.get("/guide/mine")
async def guide_mine(user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    lvl = user.guide_profile.level
    tours = (await db.execute(select(Tour).where(Tour.guide_id == user.id, Tour.status != TourStatus.draft)
                              .order_by(Tour.start_at.desc()))).scalars().all()
    out = [job_view(t, "guide", lvl, detail=True) for t in tours]
    apps = (await db.execute(select(TourApplication).where(
        TourApplication.user_id == user.id, TourApplication.kind == AppKind.practice,
        TourApplication.status.in_([AppStatus.pending, AppStatus.approved])))).scalars().all()
    for a in apps:
        t = await db.get(Tour, a.tour_id)
        v = job_view(t, "guide", 1, detail=a.status == AppStatus.approved)
        v.update(is_practice=True, application_status=a.status.value)
        out.append(v)
    return out


@router.post("/tours/{tour_id}/guide/accept")
async def guide_accept(tour_id: int, user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    """Birinchi rozi bo'lgan gidni tizim avtomatik tanlaydi."""
    t = await _tour(db, tour_id)
    lvl = user.guide_profile.level
    if lvl < 2 or t.min_guide_level is None or lvl < t.min_guide_level:
        raise HTTPException(403, "Bu tur sizning darajangizga mos emas")
    if aware(t.start_at) <= now():
        raise HTTPException(400, "Tur vaqti o'tgan")
    res = await db.execute(update(Tour).where(
        Tour.id == tour_id, Tour.guide_id.is_(None), Tour.status == TourStatus.open
    ).values(guide_id=user.id))
    if res.rowcount == 0:
        await db.rollback()
        raise HTTPException(409, "Bu turni boshqa gid allaqachon oldi")
    await db.commit()
    await db.refresh(t)
    recompute_status(t)
    await notify(db, [t.created_by], f"«{t.title}» turini gid {user.full_name} qabul qildi.")
    await db.commit()
    return job_view(t, "guide", lvl, detail=True)


@router.post("/tours/{tour_id}/practice/apply", status_code=201)
async def practice_apply(tour_id: int, user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    if user.guide_profile.level != 1:
        raise HTTPException(403, "Amaliyot arizasi faqat 1-daraja uchun")
    if user.guide_profile.practice_done:
        raise HTTPException(400, "Amaliyot tur allaqachon bajarilgan")
    t = await _tour(db, tour_id)
    if t.status not in (TourStatus.open, TourStatus.ready) or aware(t.start_at) <= now():
        raise HTTPException(400, "Bu turga ariza berib bo'lmaydi")
    if aware(t.start_at) - now() > timedelta(hours=48):
        raise HTTPException(400, "Amaliyot arizasi faqat yaqin (48 soat ichidagi) turlarga beriladi")
    exists = (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == t.id, TourApplication.user_id == user.id,
        TourApplication.kind == AppKind.practice))).scalar_one_or_none()
    if exists and exists.status in (AppStatus.pending, AppStatus.approved):
        raise HTTPException(409, "Ariza allaqachon yuborilgan")
    if exists:
        exists.status = AppStatus.pending
    else:
        db.add(TourApplication(tour_id=t.id, user_id=user.id, kind=AppKind.practice))
    await notify(db, [t.created_by], f"Amaliyotchi gid {user.full_name} ({user.phone}) «{t.title}» turiga ariza yubordi.", user.id)
    await db.commit()
    return {"ok": True}


# ---------------- HAYDOVCHI ----------------
@router.get("/driver")
async def driver_list(
    day: str = Query("all", pattern="^(all|today|tomorrow)$"),
    state: str = Query("free", pattern="^(free|mine)$"),
    user: User = Depends(driver_only), db: AsyncSession = Depends(get_db),
):
    """state=free: band qilinmagan, state=mine: o'zim olgan (band qilingan). day=tomorrow — ertangi ishlar."""
    q = select(Tour).where(Tour.status.in_([TourStatus.open, TourStatus.ready, TourStatus.completed]))
    if state == "free":
        q = q.where(Tour.status.in_([TourStatus.open, TourStatus.ready]), Tour.driver_id.is_(None), Tour.start_at > now())
    else:  # o'zi olgan ishlar + admin tasdig'ini kutayotgan arizalari
        pend = select(TourApplication.tour_id).where(
            TourApplication.user_id == user.id, TourApplication.kind == AppKind.driver,
            TourApplication.status == AppStatus.pending)
        q = q.where(or_(Tour.driver_id == user.id, Tour.id.in_(pend)))
    if day != "all":
        from datetime import timedelta as td
        d = today_local() + (td(days=1) if day == "tomorrow" else td(0))
        s, e = local_day_range(d)
        q = q.where(Tour.start_at >= s, Tour.start_at < e)
    tours = (await db.execute(q.order_by(Tour.start_at))).scalars().all()
    applied = set((await db.execute(select(TourApplication.tour_id).where(
        TourApplication.user_id == user.id, TourApplication.kind == AppKind.driver,
        TourApplication.status == AppStatus.pending))).scalars().all())
    out = []
    for t in tours:
        v = job_view(t, "driver", detail=t.driver_id == user.id)
        v["applied"] = t.id in applied
        v["pending"] = t.driver_id != user.id and t.id in applied  # admin tasdig'i kutilmoqda
        out.append(v)
    return out


@router.post("/tours/{tour_id}/driver/apply", status_code=201)
async def driver_apply(tour_id: int, user: User = Depends(driver_only), db: AsyncSession = Depends(get_db)):
    t = await _tour(db, tour_id)
    if t.status not in (TourStatus.open, TourStatus.ready) or t.driver_id or aware(t.start_at) <= now():
        raise HTTPException(400, "Bu turga ariza berib bo'lmaydi")
    app = (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == t.id, TourApplication.user_id == user.id,
        TourApplication.kind == AppKind.driver))).scalar_one_or_none()
    if app and app.status == AppStatus.pending:
        raise HTTPException(409, "Ariza allaqachon yuborilgan")
    if app:
        app.status = AppStatus.pending
    else:
        db.add(TourApplication(tour_id=t.id, user_id=user.id, kind=AppKind.driver))
    rating = await driver_rating(db, user.id)
    await notify(db, [t.created_by], f"Haydovchi {user.full_name} «{t.title}» turini qabul qildi. "
                 f"Mashina: {user.car_model}, reyting: {rating if rating else 'hali yo`q'}. Tasdiqlang.", user.id)
    await db.commit()
    return {"ok": True, "message": "Ariza yuborildi, admin tasdig'ini kuting"}


@router.delete("/tours/{tour_id}/driver/apply", status_code=204)
async def driver_withdraw_application(tour_id: int, user: User = Depends(driver_only), db: AsyncSession = Depends(get_db)):
    app = (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == tour_id, TourApplication.user_id == user.id,
        TourApplication.kind == AppKind.driver, TourApplication.status == AppStatus.pending))).scalar_one_or_none()
    if app is None:
        raise HTTPException(404, "Kutilayotgan ariza yo'q")
    app.status = AppStatus.withdrawn
    await db.commit()


# ---------------- UMUMIY (gid + haydovchi) ----------------
@router.post("/tours/{tour_id}/cancel")
async def worker_cancel(tour_id: int, data: ReasonIn, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    """Boshlanishiga 24 soatdan kam qolsa o'zi bekor qila olmaydi — admin orqali bekor qilinadi."""
    t = await _tour(db, tour_id)
    if t.status not in (TourStatus.open, TourStatus.ready):
        raise HTTPException(400, "Tur faol emas")
    role = None
    if t.guide_id == user.id:
        role = "guide"
    elif t.driver_id == user.id:
        role = "driver"
    practice = None
    if role is None and user.role == Role.guide:
        practice = (await db.execute(select(TourApplication).where(
            TourApplication.tour_id == t.id, TourApplication.user_id == user.id,
            TourApplication.kind == AppKind.practice,
            TourApplication.status.in_([AppStatus.pending, AppStatus.approved])))).scalar_one_or_none()
    if role is None and practice is None:
        raise HTTPException(404, "Siz bu turda ishtirok etmaysiz")
    if not hours_left_ok(t):
        admin = await db.get(User, t.created_by)
        raise HTTPException(
            400,
            f"Tur boshlanishiga 24 soatdan kam vaqt qolgan, o'zingiz bekor qila olmaysiz. "
            f"Admin {admin.full_name} ({admin.phone}) bilan bog'laning — bekor qilishni admin amalga oshiradi.",
        )
    if practice:
        practice.status = AppStatus.withdrawn
        db.add(TourCancellation(tour_id=t.id, user_id=user.id, role="practice", by_user_id=user.id, reason=data.reason))
    else:
        from app.api.v1.tours import _free_slot
        await _free_slot(db, t, role, user.id, user.id, False, data.reason)
    await notify(db, [t.created_by], f"{user.full_name} «{t.title}» ({t.start_at:%d.%m %H:%M}) turidan voz kechdi. "
                 f"Sabab: {data.reason or '—'}. O'rin bo'shadi, qayta yuborishingiz mumkin.", user.id)
    await db.commit()
    return {"ok": True}


@router.post("/tours/{tour_id}/late")
async def report_late(tour_id: int, data: LateIn, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    t = await _tour(db, tour_id)
    if user.id not in (t.guide_id, t.driver_id):
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
    t.late_reported = True
    await notify(db, [t.created_by], f"Kechikish xabari: {user.full_name}, «{t.title}». {data.note}", user.id)
    await db.commit()
    return {"ok": True}


@router.post("/tours/{tour_id}/complete")
async def complete(tour_id: int, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    """Gid va haydovchi ikkalasi «muvaffaqiyatli» tugmasini bossa tur yakunlanadi."""
    t = await _tour(db, tour_id)
    if t.status != TourStatus.ready:
        raise HTTPException(400, "Tur yakunlash holatida emas (gid va haydovchi tayinlangan bo'lishi kerak)")
    if aware(t.start_at) > now():
        raise HTTPException(400, "Tur hali boshlanmagan")
    if user.id == t.guide_id:
        t.guide_confirmed_at = now()
    elif user.id == t.driver_id:
        t.driver_confirmed_at = now()
    else:
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
    if t.guide_confirmed_at and t.driver_confirmed_at:
        await finalize_tour(db, t)
    await db.commit()
    return {"status": t.status.value, "guide_confirmed": bool(t.guide_confirmed_at),
            "driver_confirmed": bool(t.driver_confirmed_at)}


@router.post("/tours/{tour_id}/rate-driver")
async def rate_driver(tour_id: int, data: RateIn, user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    t = await _tour(db, tour_id)
    if t.guide_id != user.id or t.status != TourStatus.completed or not t.driver_id:
        raise HTTPException(400, "Faqat yakunlangan o'z turingizdagi haydovchini baholay olasiz")
    if (await db.execute(select(Rating).where(Rating.tour_id == t.id))).scalar_one_or_none():
        raise HTTPException(409, "Allaqachon baholangan")
    db.add(Rating(tour_id=t.id, driver_id=t.driver_id, guide_id=user.id, stars=data.stars))
    await db.commit()
    return {"ok": True}
