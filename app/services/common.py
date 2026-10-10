from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.languages import LANGUAGES
from app.core.timeutil import CANCEL_LIMIT, TZ, aware, now
from app.models import (
    AppSetting, GuideProfile, LevelRate, Message, Rating, Role, Tour, TourStatus, UsdRateLog, User,
)

SETTING_DEFAULTS = {"admin_fee_usd": "2"}
DEFAULT_USD_RATE = 12700.0


async def get_setting(db: AsyncSession, key: str) -> str:
    row = await db.get(AppSetting, key)
    return row.value if row else SETTING_DEFAULTS[key]


async def notify(db: AsyncSession, user_ids, body: str, sender_id: int | None = None):
    for uid in set(user_ids):
        db.add(Message(sender_id=sender_id, recipient_id=uid, body=body))


async def driver_rating(db: AsyncSession, driver_id: int) -> float | None:
    v = (await db.execute(select(func.avg(Rating.stars)).where(Rating.driver_id == driver_id))).scalar_one()
    return round(float(v), 2) if v is not None else None


async def get_usd_rate(db: AsyncSession) -> float:
    row = (await db.execute(select(UsdRateLog).order_by(UsdRateLog.id.desc()).limit(1))).scalar_one_or_none()
    return float(row.rate) if row else DEFAULT_USD_RATE


async def apply_price(db: AsyncSession, t: Tour, amount: float, currency: str):
    """Narx so'mda yoki dollarda kiritiladi; hisob-kitob uchun total_price har doim so'mda."""
    t.price_currency, t.price_original = currency, amount
    if currency == "USD":
        rate = await get_usd_rate(db)
        t.usd_rate_used = rate
        t.total_price = int(round(amount * rate))
    else:
        t.usd_rate_used = None
        t.total_price = int(round(amount))


async def effective_rate(db: AsyncSession, level: int) -> tuple[int, int] | None:
    """Daraja uchun amaldagi eng kam summa: o'zining va undan pastki (3+) darajalar summalarining eng kattasi.
    Masalan 4-darajaga 300 000 belgilangan bo'lsa, alohida summasi yo'q 5-daraja uchun ham 300 000.
    Qaytaradi (summa, qaysi daraja uchun belgilangan)."""
    rows = (await db.execute(select(LevelRate).where(LevelRate.level >= 3, LevelRate.level <= level))).scalars().all()
    if not rows:
        return None
    top = max(rows, key=lambda r: (r.amount, -r.level))
    return top.amount, top.level


async def check_floor(db: AsyncSession, min_level: int, amount: int):
    """Admin tanlangan daraja uchun amaldagi eng kam summadan kam taklif yubora olmaydi.
    1-2 darajalar bepul, ularga pol yo'q."""
    if min_level >= 3:
        eff = await effective_rate(db, min_level)
        if eff is None:
            raise HTTPException(400, "Super admin hali daraja summalarini belgilamagan")
        floor, src = eff
        if amount < floor:
            raise HTTPException(
                400, f"{min_level}-daraja uchun taklif {floor:,} so'mdan kam bo'lishi mumkin emas "
                     f"({src}-daraja uchun belgilangan summa)")


def recompute_status(t: Tour):
    if t.status in (TourStatus.open, TourStatus.ready):
        t.status = TourStatus.ready if (t.guide_id and t.driver_id) else TourStatus.open


def hours_left_ok(t: Tour) -> bool:
    """Boshlanishiga kamida 24 soat qolgan bo'lsa ishchi o'zi bekor qila oladi."""
    return aware(t.start_at) - now() >= CANCEL_LIMIT


def fmt_dt(dt) -> str:
    return aware(dt).astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def offer_text(t: Tour, role: str, amount: int) -> str:
    route = " → ".join(f"{s.address} ({s.arrival_time})" if s.arrival_time else s.address for s in t.stops) or t.pickup_address
    note = t.guide_note if role == "guide" else t.driver_note
    extra = f"\nOdam soni: {t.pax_count}" if role == "driver" else ""
    return (
        f"Yangi tur: {t.title} ({LANGUAGES.get(t.language, t.language)} tili)\nSana: {fmt_dt(t.start_at)}\nYo'nalish: {route}\n"
        f"Narx: {amount:,} so'm{extra}\n{note}".strip()
    )


async def level_up_check(db: AsyncSession, gp: GuideProfile):
    """Daraja avtomatik ko'tarilishi: 1->2 (ikki chekboks), 2->3 (5 tur), 3->4 (15 tur)."""
    old = gp.level
    if gp.level == 1 and gp.practice_done and gp.interview_passed:
        gp.level, gp.level_tours = 2, 0
    elif gp.level == 2 and gp.level_tours >= 5:
        gp.level, gp.level_tours = 3, 0
    elif gp.level == 3 and gp.level_tours >= 15:
        gp.level, gp.level_tours = 4, 0
    if gp.level != old:
        await notify(db, [gp.user_id], f"Tabriklaymiz! Siz {gp.level}-darajaga ko'tarildingiz.")


async def finalize_tour(db: AsyncSession, t: Tour):
    """Gid ham, haydovchi ham tasdiqlagach: hisob-kitob, haqlar, daraja."""
    from app.models import AppKind, AppStatus, EarnKind, Earning, TourApplication

    t.status = TourStatus.completed
    t.completed_at = now()

    gp = (await db.execute(select(GuideProfile).where(GuideProfile.user_id == t.guide_id))).scalar_one()
    guide_pay = t.guide_amount if gp.level >= 3 else 0   # 1-2 daraja tekin
    if t.price_currency == "USD":  # yakuniy kurs: tur yakunlangan paytdagi amaldagi kurs
        await apply_price(db, t, t.price_original, "USD")
    t.platform_fee = int(round(t.total_price * float(t.platform_percent) / 100))
    t.guide_cost = guide_pay
    t.driver_cost = t.driver_amount

    admin = await db.get(User, t.created_by)
    admin_cost = 0
    if admin and admin.role == Role.admin:
        admin_cost = int(round(float(await get_setting(db, "admin_fee_usd")) * await get_usd_rate(db)))
    t.admin_cost = admin_cost
    t.profit = t.total_price - t.platform_fee - guide_pay - t.driver_amount - admin_cost

    from app.models import EarnKind
    if guide_pay > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.guide_id, kind=EarnKind.guide, amount=guide_pay))
    if t.driver_amount > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.driver_id, kind=EarnKind.driver, amount=t.driver_amount))
    if admin_cost > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.created_by, kind=EarnKind.admin, amount=admin_cost))

    gp.completed_tours += 1
    gp.level_tours += 1
    await level_up_check(db, gp)

    # amaliyotchi (1-daraja) gidlar
    apps = (await db.execute(select(TourApplication).where(
        TourApplication.tour_id == t.id, TourApplication.kind == AppKind.practice,
        TourApplication.status == AppStatus.approved))).scalars().all()
    for a in apps:
        pgp = (await db.execute(select(GuideProfile).where(GuideProfile.user_id == a.user_id))).scalar_one_or_none()
        if pgp and pgp.level == 1:
            pgp.practice_done = True
            await level_up_check(db, pgp)

    await notify(db, [t.created_by], f"«{t.title}» ({fmt_dt(t.start_at)}) muvaffaqiyatli yakunlandi."
                 + (" Kechikish haqida xabar bo'lgan: jarima bor-yo'qligini belgilang." if t.late_reported else ""))
