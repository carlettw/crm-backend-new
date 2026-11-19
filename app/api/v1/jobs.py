from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.languages import LANGUAGES
from app.core.regions import REGIONS
from app.core.deps import get_current_user, require_roles
from app.core.timeutil import START_GRACE, aware, local_day_range, now, today_local
from app.db.session import get_db
from app.models import (
    AppKind, AppStatus, GuideProfile, Rating, Role, Tour, TourApplication, TourCancellation,
    TourComment, TourStatus, User,
)
from app.schemas.tour import CommentIn, LateIn, RateIn, ReasonIn
from app.services.common import (
    driver_rating, ensure_free, fmt_dt, hours_left_ok, notify, recompute_status,
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
def _gp(user: User):
    if user.guide_profile is None:
        raise HTTPException(404, "Gid profili topilmadi. Super adminga murojaat qiling")
    return user.guide_profile


@router.get("/guide/available")
async def guide_available(limit: int = Query(100, ge=1, le=300), offset: int = Query(0, ge=0),
                          user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    """2+ daraja: o'z darajasiga mos, hali gid olmagan turlar."""
    lvl = _gp(user).level
    if lvl < 2:
        return []
    q = select(Tour).where(Tour.status == TourStatus.open, Tour.guide_id.is_(None),
                           Tour.min_guide_level <= lvl, Tour.start_at > now() - START_GRACE).order_by(Tour.start_at)
    langs = user.guide_profile.languages or []
    regs = user.guide_profile.regions or []
    items = [t for t in (await db.execute(q)).scalars().all()
             if set(t.languages) <= set(langs) and (not t.region or t.region in regs)]
    return [job_view(t, "guide", lvl) for t in items[offset:offset + limit]]


@router.get("/guide/mine")
async def guide_mine(limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
                     user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    lvl = _gp(user).level
    tours = (await db.execute(select(Tour).where(Tour.guide_id == user.id, Tour.status != TourStatus.draft)
                              .order_by(Tour.start_at.desc()).limit(limit).offset(offset))).scalars().all()
    out = [job_view(t, "guide", lvl, detail=True) for t in tours]
    practice = (await db.execute(select(Tour).join(TourApplication, TourApplication.tour_id == Tour.id).where(
        TourApplication.user_id == user.id, TourApplication.kind == AppKind.practice,
        TourApplication.status == AppStatus.approved, Tour.status != TourStatus.draft)
        .order_by(Tour.start_at.desc()).limit(limit))).scalars().unique().all()  # admin biriktirgan amaliyot turlari
    for t in practice:
        v = job_view(t, "guide", 1, detail=True)
        v.update(is_practice=True)
        out.append(v)
    return out


@router.post("/tours/{tour_id}/guide/accept")
async def guide_accept(tour_id: int, user: User = Depends(guide_only), db: AsyncSession = Depends(get_db)):
    """Birinchi rozi bo'lgan gidni tizim avtomatik tanlaydi."""
    t = await _tour(db, tour_id)
    lvl = _gp(user).level
    if lvl < 2 or t.min_guide_level is None or lvl < t.min_guide_level:
        raise HTTPException(403, "Bu tur sizning darajangizga mos emas")
    if t.region and t.region not in (user.guide_profile.regions or []):
        raise HTTPException(403, f"Bu tur {REGIONS.get(t.region, t.region)} viloyatida. Profilingizda shu viloyatni qo'shing")
    missing = [LANGUAGES.get(x, x) for x in t.languages if x not in (user.guide_profile.languages or [])]
    if missing:
        raise HTTPException(403, f"Bu tur {', '.join(missing)} tilida ham o'tadi. Sizning tillaringizda yo'q — profilingizda tillarni yangilang")
    if aware(t.start_at) <= now() - START_GRACE:
        raise HTTPException(400, "Tur vaqti o'tgan")
    await ensure_free(db, user.id, t)  # shu vaqtda boshqa turi bo'lsa ololmaydi
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


# ---------------- HAYDOVCHI ----------------
@router.get("/driver")
async def driver_list(
    day: str = Query("all", pattern="^(all|today|tomorrow)$"),
    state: str = Query("free", pattern="^(free|mine)$"),
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    user: User = Depends(driver_only), db: AsyncSession = Depends(get_db),
):
    """state=free: band qilinmagan, state=mine: o'zim olgan (band qilingan). day=tomorrow — ertangi ishlar."""
    q = select(Tour).where(Tour.status.in_([TourStatus.open, TourStatus.ready, TourStatus.awaiting_approval, TourStatus.completed]))
    if state == "free":
        q = q.where(Tour.status.in_([TourStatus.open, TourStatus.ready]), Tour.driver_id.is_(None), Tour.needs_driver.is_(True), Tour.start_at > now() - START_GRACE)
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
    order = Tour.start_at if state == "free" else Tour.start_at.desc()
    tours = (await db.execute(q.order_by(order).limit(limit).offset(offset))).scalars().all()
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
    if not t.needs_driver:
        raise HTTPException(400, "Bu tur haydovchisiz (gid yolg'iz chiqadi)")
    if t.status not in (TourStatus.open, TourStatus.ready) or t.driver_id or aware(t.start_at) <= now() - START_GRACE:
        raise HTTPException(400, "Bu turga ariza berib bo'lmaydi")
    await ensure_free(db, user.id, t)
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
    if role is None:
        raise HTTPException(404, "Siz bu turda gid/haydovchi emassiz (amaliyotchini admin biriktiradi va bekor qiladi)")
    if not hours_left_ok(t):
        admin = await db.get(User, t.created_by)
        raise HTTPException(
            400,
            f"Tur boshlanishiga 24 soatdan kam vaqt qolgan, o'zingiz bekor qila olmaysiz. "
            f"Admin {admin.full_name} ({admin.phone}) bilan bog'laning — bekor qilishni admin amalga oshiradi.",
        )
    from app.api.v1.tours import _free_slot
    await _free_slot(db, t, role, user.id, user.id, False, data.reason)
    await notify(db, [t.created_by], f"{user.full_name} «{t.title}» ({fmt_dt(t.start_at)}) turidan voz kechdi. "
                 f"Sabab: {data.reason or '—'}. O'rin bo'shadi, qayta yuborishingiz mumkin.", user.id)
    await db.commit()
    return {"ok": True}


@router.post("/tours/{tour_id}/late")
async def report_late(tour_id: int, data: LateIn, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    t = await _tour(db, tour_id)
    if user.id not in (t.guide_id, t.driver_id):
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
    if t.status not in (TourStatus.open, TourStatus.ready, TourStatus.awaiting_approval):
        raise HTTPException(400, "Kechikish faqat faol tur bo'yicha xabar qilinadi")
    if aware(t.start_at) - now() > timedelta(hours=6):
        raise HTTPException(400, "Kechikish haqida tur boshlanishiga 6 soatdan kam qolganda xabar bering")
    t.late_reported = True
    await notify(db, [t.created_by], f"Kechikish xabari: {user.full_name}, «{t.title}». {data.note}", user.id)
    await db.commit()
    return {"ok": True}


@router.post("/tours/{tour_id}/complete")
async def complete(tour_id: int, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    """Gid «muvaffaqiyatli» tugmasini bossa tur admin tasdig'iga yuboriladi va adminga xabar boradi.
    Admin tasdiqlagach tur yakunlanadi, haqlar hisobga o'tadi. Haydovchi tasdig'i adminga ma'lumot sifatida qayd etiladi."""
    t = await _tour(db, tour_id)
    if t.status not in (TourStatus.open, TourStatus.ready, TourStatus.awaiting_approval):
        raise HTTPException(400, "Tur yakunlash holatida emas")
    if aware(t.start_at) > now():
        raise HTTPException(400, "Tur hali boshlanmagan")
    if user.id == t.guide_id:
        if t.status == TourStatus.awaiting_approval:
            raise HTTPException(409, "Tur allaqachon admin tasdig'iga yuborilgan")
        t.guide_confirmed_at = now()
        t.status = TourStatus.awaiting_approval
        await notify(db, [t.created_by], f"Gid {user.full_name} «{t.title}» turini yakunladi. Tasdiqlang yoki qaytaring.", user.id)
    elif user.id == t.driver_id:
        t.driver_confirmed_at = now()
        await notify(db, [t.created_by], f"Haydovchi {user.full_name} «{t.title}» turi tugaganini tasdiqladi.", user.id)
    else:
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
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


# ---------------- IZOHLAR (tur yakunlangach) ----------------
async def _participant(db, t: Tour, user: User) -> bool:
    if user.id in (t.guide_id, t.driver_id):
        return True
    return (await db.execute(select(TourApplication.id).where(
        TourApplication.tour_id == t.id, TourApplication.user_id == user.id, TourApplication.kind == AppKind.practice,
        TourApplication.status == AppStatus.approved))).first() is not None


@router.get("/tours/{tour_id}/comments")
async def my_comments(tour_id: int, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    """O'zi qoldirgan izohlar (boshqa ishchilarning izohlari ko'rinmaydi; admin va boshliq hammasini ko'radi)."""
    t = await _tour(db, tour_id)
    if not await _participant(db, t, user):
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
    rows = (await db.execute(select(TourComment).where(TourComment.tour_id == t.id, TourComment.user_id == user.id)
                             .order_by(TourComment.id))).scalars().all()
    return [dict(id=c.id, body=c.body, created_at=c.created_at) for c in rows]


@router.post("/tours/{tour_id}/comments", status_code=201)
async def add_comment(tour_id: int, data: CommentIn, user: User = Depends(worker), db: AsyncSession = Depends(get_db)):
    """Tur yakunlangach (yoki admin tasdig'ini kutayotganda) izoh qoldirish."""
    t = await _tour(db, tour_id)
    if not await _participant(db, t, user):
        raise HTTPException(403, "Siz bu turda ishtirok etmaysiz")
    if t.status not in (TourStatus.awaiting_approval, TourStatus.completed):
        raise HTTPException(400, "Izoh tur yakunlangandan keyin qoldiriladi")
    n = (await db.execute(select(func.count()).select_from(TourComment).where(
        TourComment.tour_id == t.id, TourComment.user_id == user.id))).scalar_one()
    if n >= 10:
        raise HTTPException(400, "Bir tur uchun ko'pi bilan 10 ta izoh")
    c = TourComment(tour_id=t.id, user_id=user.id, role=user.role.value + ("_practice" if user.id not in (t.guide_id, t.driver_id) else ""), body=data.body.strip())
    db.add(c)
    await notify(db, [t.created_by], f"{user.full_name} «{t.title}» turi bo'yicha izoh qoldirdi: {data.body.strip()[:120]}", user.id)
    await db.commit()
    return {"id": c.id}
