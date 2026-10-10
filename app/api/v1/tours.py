from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.languages import LANGUAGES
from app.core.ctx import Ctx, admin_ctx, get_tour_or_404, read_ctx
from app.core.timeutil import aware, now
from app.db.session import get_db
from app.models import (
    AppKind, AppStatus, Fine, GuideProfile, Role, Tour, TourApplication, TourCancellation,
    TourStatus, TourStop, User,
)
from app.schemas.tour import (
    ApplicationOut, AssignIn, CancelWorkerIn, CloneIn, FineIn, PublishIn, ReasonIn, RedispatchIn,
    TourCreate, TourOut, TourUpdate, UserIdIn,
)
from app.services.common import (
    apply_price, check_floor, driver_rating, notify, offer_text, recompute_status,
)

router = APIRouter(prefix="/tours", tags=["tours (admin/boshliq)"])


def _stops(items):
    return [TourStop(position=i, address=s.address, duration_minutes=s.duration_minutes,
                     description=s.description, location_url=s.location_url, arrival_time=s.arrival_time)
            for i, s in enumerate(items)]


@router.post("", response_model=TourOut, status_code=201)
async def create_tour(data: TourCreate, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    d = data.model_dump(exclude={"stops", "total_price", "price_currency"})
    t = Tour(**d, boss_id=ctx.boss_id, created_by=ctx.user.id, status=TourStatus.draft)
    await apply_price(db, t, data.total_price, data.price_currency)
    t.stops = _stops(data.stops)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@router.get("", response_model=list[TourOut])
async def list_tours(
    status: TourStatus | None = None,
    search: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(100, ge=1, le=300),
    offset: int = 0,
    ctx: Ctx = Depends(read_ctx),
    db: AsyncSession = Depends(get_db),
):
    q = select(Tour).where(Tour.boss_id == ctx.boss_id)
    if status:
        q = q.where(Tour.status == status)
    if search:
        q = q.where(Tour.title.ilike(f"%{search}%"))
    if date_from:
        q = q.where(Tour.start_at >= date_from)
    if date_to:
        q = q.where(Tour.start_at < date_to)
    return (await db.execute(q.order_by(Tour.start_at.desc()).limit(limit).offset(offset))).scalars().all()


@router.get("/{tour_id}", response_model=TourOut)
async def get_tour(tour_id: int, ctx: Ctx = Depends(read_ctx), db: AsyncSession = Depends(get_db)):
    return await get_tour_or_404(db, tour_id, ctx.boss_id)


@router.patch("/{tour_id}", response_model=TourOut)
async def update_tour(tour_id: int, data: TourUpdate, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status in (TourStatus.completed, TourStatus.cancelled):
        raise HTTPException(400, "Yakunlangan yoki bekor qilingan turni o'zgartirib bo'lmaydi")
    vals = data.model_dump(exclude_unset=True)
    stops = vals.pop("stops", None)
    cur, amt = vals.pop("price_currency", None), vals.pop("total_price", None)
    if cur is not None and amt is None and cur != t.price_currency:
        raise HTTPException(400, "Valyutani o'zgartirsangiz narxni ham birga yuboring")
    if cur is not None or amt is not None:
        await apply_price(db, t, amt if amt is not None else t.price_original, cur or t.price_currency)
    for k, v in vals.items():
        setattr(t, k, v)
    if stops is not None:
        t.stops = _stops(data.stops)
    if t.status != TourStatus.draft and t.min_guide_level and ("guide_amount" in vals):
        await check_floor(db, t.min_guide_level, t.guide_amount)
    await db.commit()
    await db.refresh(t)
    return t


@router.delete("/{tour_id}", status_code=204)
async def delete_tour(tour_id: int, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status != TourStatus.draft:
        raise HTTPException(400, "Faqat saqlangan (draft) turni o'chirish mumkin; yuborilganini bekor qiling")
    await db.delete(t)
    await db.commit()


@router.post("/{tour_id}/clone", response_model=TourOut, status_code=201)
async def clone_tour(tour_id: int, data: CloneIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Saqlangan turdan ishdan bir kun oldin tayyor shablon sifatida nusxa olish (xohlasa o'zgartirib)."""
    src = await get_tour_or_404(db, tour_id, ctx.boss_id)
    cols = ["title", "language", "description", "pickup_address", "start_at", "platform_percent",
            "guide_amount", "driver_amount", "guide_note", "driver_note", "tourist_name",
            "tourist_phone", "tourist_email", "messenger", "pax_count"]
    vals = {c: getattr(src, c) for c in cols}
    over = data.model_dump(exclude_unset=True, exclude={"stops"})
    cur, amt = over.pop("price_currency", None), over.pop("total_price", None)
    vals.update(over)
    t = Tour(**vals, boss_id=ctx.boss_id, created_by=ctx.user.id, status=TourStatus.draft)
    if cur is not None and amt is None and cur != src.price_currency:
        raise HTTPException(400, "Valyutani o'zgartirsangiz narxni ham birga yuboring")
    # nusxa joriy kurs bilan qayta hisoblanadi
    await apply_price(db, t, amt if amt is not None else src.price_original, cur or src.price_currency)
    if data.stops is not None:
        t.stops = _stops(data.stops)
    else:
        t.stops = [TourStop(position=s.position, address=s.address, duration_minutes=s.duration_minutes,
                            description=s.description, location_url=s.location_url, arrival_time=s.arrival_time)
                   for s in src.stops]
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _dispatch(db: AsyncSession, t: Tour, role: str):
    if role == "guide":
        rows = (await db.execute(
            select(GuideProfile).join(User, User.id == GuideProfile.user_id).where(
                User.is_active.is_(True), GuideProfile.level >= max(2, t.min_guide_level or 2))
        )).scalars().all()
        ids = [g.user_id for g in rows if t.language in (g.languages or [])]  # faqat shu tilni biladiganlar
        await notify(db, ids, offer_text(t, "guide", t.guide_amount), t.created_by)
    else:
        ids = (await db.execute(select(User.id).where(User.role == Role.driver, User.is_active.is_(True)))).scalars().all()
        await notify(db, ids, offer_text(t, "driver", t.driver_amount), t.created_by)
    return len(ids)


@router.post("/{tour_id}/publish", response_model=TourOut)
async def publish(tour_id: int, data: PublishIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Turni gidlarga (tanlangan va undan yuqori daraja) va haydovchilarga yuborish."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status != TourStatus.draft:
        raise HTTPException(400, "Faqat saqlangan (draft) turni yuborish mumkin")
    if aware(t.start_at) <= now():
        raise HTTPException(400, "Tur boshlanish vaqti o'tib ketgan")
    await check_floor(db, data.min_guide_level, t.guide_amount)
    t.min_guide_level = data.min_guide_level
    t.status = TourStatus.open
    n = await _dispatch(db, t, "guide")
    await _dispatch(db, t, "driver")
    await db.commit()
    await db.refresh(t)
    t.notified_guides = n
    return t


@router.post("/{tour_id}/redispatch", response_model=TourOut)
async def redispatch(tour_id: int, data: RedispatchIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Bo'sh qolgan o'rin uchun turni qayta yuborish (xohlasa daraja/summani o'zgartirib)."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status not in (TourStatus.open, TourStatus.ready):
        raise HTTPException(400, "Tur faol emas")
    if data.role == "guide":
        if t.guide_id:
            raise HTTPException(400, "Gid allaqachon tayinlangan; avval uni bekor qiling")
        if data.min_guide_level:
            t.min_guide_level = data.min_guide_level
        if data.guide_amount is not None:
            t.guide_amount = data.guide_amount
        await check_floor(db, t.min_guide_level or 2, t.guide_amount)
    elif t.driver_id:
        raise HTTPException(400, "Haydovchi allaqachon tayinlangan; avval uni bekor qiling")
    n = await _dispatch(db, t, data.role)
    await db.commit()
    await db.refresh(t)
    if data.role == "guide":
        t.notified_guides = n
    return t


@router.post("/{tour_id}/assign", response_model=TourOut)
async def assign(tour_id: int, data: AssignIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Admin aniq gid/haydovchini tayinlaydi (jumladan avval bekor qilingan ishchini qaytarish)."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status not in (TourStatus.open, TourStatus.ready):
        raise HTTPException(400, "Tur faol emas")
    u = await db.get(User, data.user_id)
    if u is None or not u.is_active or u.role.value != data.role:
        raise HTTPException(400, f"Foydalanuvchi faol {data.role} emas")
    if data.role == "guide":
        if t.guide_id and t.guide_id != u.id:
            raise HTTPException(400, "Gid allaqachon tayinlangan")
        if u.guide_profile.level < 2:
            raise HTTPException(400, "1-daraja gid faqat amaliyotchi sifatida qatnashadi")
        if t.language not in (u.guide_profile.languages or []):
            raise HTTPException(400, f"Gid {LANGUAGES.get(t.language, t.language)} tilini bilmaydi")
        t.guide_id = u.id
    else:
        if t.driver_id and t.driver_id != u.id:
            raise HTTPException(400, "Haydovchi allaqachon tayinlangan")
        t.driver_id = u.id
        apps = (await db.execute(select(TourApplication).where(
            TourApplication.tour_id == t.id, TourApplication.kind == AppKind.driver,
            TourApplication.status == AppStatus.pending))).scalars().all()
        for a in apps:
            a.status = AppStatus.approved if a.user_id == u.id else AppStatus.rejected
    recompute_status(t)
    await notify(db, [u.id], f"Sizga tur tayinlandi: «{t.title}».", ctx.user.id)
    await db.commit()
    await db.refresh(t)
    return t


async def _free_slot(db, t: Tour, role: str, user_id: int, by_user: int, by_admin: bool, reason: str):
    if role == "guide":
        t.guide_id = None
        t.guide_confirmed_at = None
    else:
        t.driver_id = None
        t.driver_confirmed_at = None
        apps = (await db.execute(select(TourApplication).where(
            TourApplication.tour_id == t.id, TourApplication.user_id == user_id,
            TourApplication.kind == AppKind.driver))).scalars().all()
        for a in apps:
            a.status = AppStatus.withdrawn
    db.add(TourCancellation(tour_id=t.id, user_id=user_id, role=role, by_user_id=by_user,
                            by_admin=by_admin, reason=reason))
    recompute_status(t)


@router.post("/{tour_id}/cancel-worker", response_model=TourOut)
async def cancel_worker(tour_id: int, data: CancelWorkerIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """Admin gid/haydovchini istalgan vaqtda bekor qila oladi (24 soatlik cheklov faqat ishchining o'ziga)."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status not in (TourStatus.open, TourStatus.ready):
        raise HTTPException(400, "Tur faol emas")
    uid = t.guide_id if data.role == "guide" else t.driver_id
    if not uid:
        raise HTTPException(400, f"Bu turda {data.role} tayinlanmagan")
    await _free_slot(db, t, data.role, uid, ctx.user.id, True, data.reason)
    await notify(db, [uid], f"«{t.title}» turi bo'yicha ishtirokingiz admin tomonidan bekor qilindi."
                 + (f" Sabab: {data.reason}" if data.reason else ""), ctx.user.id)
    await db.commit()
    await db.refresh(t)
    return t


@router.post("/{tour_id}/cancel", response_model=TourOut)
async def cancel_tour(tour_id: int, data: ReasonIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status in (TourStatus.completed, TourStatus.cancelled):
        raise HTTPException(400, "Tur allaqachon yakunlangan yoki bekor qilingan")
    ids = [x for x in (t.guide_id, t.driver_id) if x]
    t.status = TourStatus.cancelled
    await notify(db, ids, f"«{t.title}» ({t.start_at:%d.%m %H:%M}) turi bekor qilindi."
                 + (f" Sabab: {data.reason}" if data.reason else ""), ctx.user.id)
    await db.commit()
    await db.refresh(t)
    return t


# ---------- arizalar (haydovchi, amaliyotchi gid) ----------
async def _app_out(db, a: TourApplication) -> ApplicationOut:
    u = a.user
    return ApplicationOut(
        id=a.id, user_id=u.id, full_name=u.full_name, phone=u.phone, kind=a.kind, status=a.status,
        car_model=u.car_model,
        rating=await driver_rating(db, u.id) if u.role == Role.driver else None,
        guide_level=u.guide_level,
    )


@router.get("/{tour_id}/applications", response_model=list[ApplicationOut])
async def applications(tour_id: int, ctx: Ctx = Depends(read_ctx), db: AsyncSession = Depends(get_db)):
    await get_tour_or_404(db, tour_id, ctx.boss_id)
    apps = (await db.execute(select(TourApplication).where(TourApplication.tour_id == tour_id)
                             .order_by(TourApplication.id))).scalars().all()
    return [await _app_out(db, a) for a in apps]


@router.post("/{tour_id}/driver/approve", response_model=TourOut)
async def approve_driver(tour_id: int, data: UserIdIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status not in (TourStatus.open, TourStatus.ready) or t.driver_id:
        raise HTTPException(400, "Haydovchi tayinlab bo'lmaydi (tur faol emas yoki haydovchi bor)")
    app = (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == t.id, TourApplication.user_id == data.user_id,
        TourApplication.kind == AppKind.driver, TourApplication.status == AppStatus.pending))).scalar_one_or_none()
    if app is None:
        raise HTTPException(404, "Bunday ariza topilmadi")
    return await assign(tour_id, AssignIn(role="driver", user_id=data.user_id), ctx, db)


@router.post("/{tour_id}/applications/{app_id}/{action}", response_model=ApplicationOut)
async def decide_application(tour_id: int, app_id: int, action: str, ctx: Ctx = Depends(admin_ctx),
                             db: AsyncSession = Depends(get_db)):
    """action = approve | reject. Amaliyotchi gid uchun tasdiqlash; haydovchi uchun rad etish."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    app = await db.get(TourApplication, app_id)
    if app is None or app.tour_id != t.id or app.status != AppStatus.pending:
        raise HTTPException(404, "Kutilayotgan ariza topilmadi")
    if action == "reject":
        app.status = AppStatus.rejected
        await notify(db, [app.user_id], f"«{t.title}» turiga arizangiz rad etildi.", ctx.user.id)
    elif action == "approve" and app.kind == AppKind.practice:
        app.status = AppStatus.approved
        await notify(db, [app.user_id], f"«{t.title}» turiga amaliyotchi sifatida tasdiqlandingiz. "
                     f"Sana: {t.start_at:%d.%m.%Y %H:%M}, manzil: {t.pickup_address}", ctx.user.id)
    else:
        raise HTTPException(400, "Haydovchini /driver/approve orqali tasdiqlang")
    await db.commit()
    await db.refresh(app)
    return await _app_out(db, app)


# ---------- jarimalar ----------
@router.post("/{tour_id}/fines", status_code=201)
async def add_fine(tour_id: int, data: FineIn, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    if t.status != TourStatus.completed:
        raise HTTPException(400, "Jarima tur yakunlangandan keyin belgilanadi")
    if data.user_id not in (t.guide_id, t.driver_id):
        raise HTTPException(400, "Jarima faqat shu turdagi gid yoki haydovchiga belgilanadi")
    db.add(Fine(boss_id=t.boss_id, tour_id=t.id, user_id=data.user_id, amount=data.amount,
                reason=data.reason, created_by=ctx.user.id))
    t.fine_decided = True
    await notify(db, [data.user_id], f"«{t.title}» turi uchun {data.amount:,} so'm jarima belgilandi. {data.reason}", ctx.user.id)
    await db.commit()
    return {"ok": True}


@router.post("/{tour_id}/fines/skip", status_code=204)
async def skip_fine(tour_id: int, ctx: Ctx = Depends(admin_ctx), db: AsyncSession = Depends(get_db)):
    """«Jarima bormi?» savoliga «yo'q» javobi."""
    t = await get_tour_or_404(db, tour_id, ctx.boss_id)
    t.fine_decided = True
    await db.commit()
