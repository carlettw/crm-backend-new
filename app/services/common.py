from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.languages import LANGUAGES
from app.core.regions import REGIONS
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
        t.status = TourStatus.ready if (t.guide_id and (t.driver_id or not t.needs_driver)) else TourStatus.open


def hours_left_ok(t: Tour) -> bool:
    """Boshlanishiga kamida 24 soat qolgan bo'lsa ishchi o'zi bekor qila oladi."""
    return aware(t.start_at) - now() >= CANCEL_LIMIT


def fmt_dt(dt) -> str:
    return aware(dt).astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def left_text(h: float) -> str:
    if h <= 0:
        return "allaqachon boshlangan"
    hh, mm = int(h), int(round((h - int(h)) * 60))
    return " ".join(x for x in (f"{hh} soat" if hh else "", f"{mm} daqiqa" if mm or not hh else "") if x)


def offer_text(t: Tour, role: str, amount: int) -> str:
    route = " → ".join(f"{s.address} ({s.arrival_time})" if s.arrival_time else s.address for s in t.stops) or t.pickup_address
    note = t.guide_note if role == "guide" else t.driver_note
    groups = ", ".join(f"{LANGUAGES.get(g.language, g.language)} — {g.pax_count} kishi" for g in t.groups) or f"{t.pax_count} kishi"
    langs = ", ".join(LANGUAGES.get(x, x) for x in t.languages)
    urgent = ""
    if t.hours_left < 24:
        urgent = (f"⚡ SHOSHILINCH! Tur boshlanishiga {left_text(t.hours_left)} qoldi. "
                  "24 soatdan kam qolgani uchun qabul qilgach o'zingiz bekor qila olmaysiz.\n")
    return (
        f"{urgent}Yangi tur: {t.title} ({langs})\nViloyat: {REGIONS.get(t.region, '—') if t.region else '—'}\nSana: {fmt_dt(t.start_at)}\nYo'nalish: {route}\n"
        f"Guruhlar: {groups} (jami {t.pax_count})\nNarx: {amount:,} so'm\n{note}".strip()
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


async def finalize_tour(db: AsyncSession, t: Tour, by_admin: bool = False):
    """Admin tasdiqlagach (yoki admin o'zi yakunlasa): hisob-kitob, haqlar, daraja.
    Gid/haydovchi bo'lmasligi mumkin (haydovchisiz tur yoki admin hech kimsiz yakunlagan)."""
    from app.models import AppKind, AppStatus, EarnKind, Earning, TourApplication

    t.status = TourStatus.completed
    t.completed_at = now()

    gp = None
    if t.guide_id:
        gp = (await db.execute(select(GuideProfile).where(GuideProfile.user_id == t.guide_id))).scalar_one_or_none()
    guide_pay = t.guide_amount if (gp and gp.level >= 3) else 0   # 1-2 daraja tekin
    driver_pay = t.driver_amount if (t.driver_id and t.needs_driver) else 0
    if t.price_currency == "USD":  # yakuniy kurs: tur yakunlangan paytdagi amaldagi kurs
        await apply_price(db, t, t.price_original, "USD")
    t.platform_fee = int(round(t.total_price * float(t.platform_percent) / 100))
    t.guide_cost = guide_pay
    t.driver_cost = driver_pay

    admin = await db.get(User, t.created_by)
    admin_cost = 0
    if admin and admin.role == Role.admin:
        admin_cost = int(round(float(await get_setting(db, "admin_fee_usd")) * await get_usd_rate(db)))
    t.admin_cost = admin_cost
    t.profit = t.total_price - t.platform_fee - guide_pay - driver_pay - admin_cost

    if guide_pay > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.guide_id, kind=EarnKind.guide, amount=guide_pay))
    if driver_pay > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.driver_id, kind=EarnKind.driver, amount=driver_pay))
    if admin_cost > 0:
        db.add(Earning(tour_id=t.id, boss_id=t.boss_id, user_id=t.created_by, kind=EarnKind.admin, amount=admin_cost))

    if gp:
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

    # pul hisobga o'tganini ishchilarga bildirish
    who = "Admin tomonidan yakunlandi." if by_admin else "Admin tasdiqladi."
    if t.guide_id:
        await notify(db, [t.guide_id], f"«{t.title}» yakunlandi. {who}" + (f" Hisobingizga {guide_pay:,} so'm qo'shildi." if guide_pay else ""), t.created_by)
    if t.driver_id and t.needs_driver:
        await notify(db, [t.driver_id], f"«{t.title}» yakunlandi. {who}" + (f" Hisobingizga {driver_pay:,} so'm qo'shildi." if driver_pay else ""), t.created_by)
    if not by_admin:
        await notify(db, [t.created_by], f"«{t.title}» ({fmt_dt(t.start_at)}) yakunlandi."
                     + (" Kechikish haqida xabar bo'lgan: jarima bor-yo'qligini belgilang." if t.late_reported else ""))
