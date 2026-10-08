from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.timeutil import now, period_range, today_local
from app.db.session import get_db
from app.models import (
    BossAdmin, EarnKind, Earning, Fine, Payment, PayStatus, Role, Tour, TourStatus, User,
)
from app.services.common import get_usd_rate, notify

router = APIRouter(tags=["boshliq"])
boss_only = require_roles(Role.boss)


class AdminIdIn(BaseModel):
    admin_id: int


# ---------- adminlarni biriktirish ----------
@router.get("/admins")
async def all_admins(user: User = Depends(require_roles(Role.boss, Role.super_admin)), db: AsyncSession = Depends(get_db)):
    """Tizimdagi administratorlar (boshliq biriktirish uchun tanlaydi)."""
    rows = (await db.execute(select(User).where(User.role == Role.admin, User.is_active.is_(True)))).scalars().all()
    return [{"id": u.id, "full_name": u.full_name, "username": u.username, "phone": u.phone} for u in rows]


@router.get("/boss/admins")
async def my_admins(user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    ids = (await db.execute(select(BossAdmin.admin_id).where(BossAdmin.boss_id == user.id))).scalars().all()
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all() if ids else []
    return [{"id": u.id, "full_name": u.full_name, "username": u.username, "phone": u.phone} for u in rows]


@router.post("/boss/admins", status_code=201)
async def add_admin(data: AdminIdIn, user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    admin = await db.get(User, data.admin_id)
    if admin is None or admin.role != Role.admin or not admin.is_active:
        raise HTTPException(400, "Faol administrator topilmadi")
    if await db.get(BossAdmin, (user.id, admin.id)):
        raise HTTPException(409, "Bu admin allaqachon biriktirilgan")
    db.add(BossAdmin(boss_id=user.id, admin_id=admin.id))
    await notify(db, [admin.id], f"Sizga boshliq {user.full_name} biriktirildi.", user.id)
    await db.commit()
    return {"ok": True}


@router.delete("/boss/admins/{admin_id}", status_code=204)
async def remove_admin(admin_id: int, user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    link = await db.get(BossAdmin, (user.id, admin_id))
    if link is None:
        raise HTTPException(404, "Bunday biriktirish yo'q")
    await db.delete(link)
    await db.commit()


@router.get("/me/bosses")
async def my_bosses(user: User = Depends(require_roles(Role.admin)), db: AsyncSession = Depends(get_db)):
    """Admin kirganda unga biriktirilgan boshliqlar ro'yxati."""
    ids = (await db.execute(select(BossAdmin.boss_id).where(BossAdmin.admin_id == user.id))).scalars().all()
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all() if ids else []
    return [{"id": u.id, "full_name": u.full_name, "username": u.username} for u in rows]


# ---------- analitika ----------
@router.get("/boss/analytics")
async def analytics(
    period: str = Query("week", pattern="^(day|week|month)$"),
    anchor: date | None = None,
    user: User = Depends(boss_only), db: AsyncSession = Depends(get_db),
):
    """Kunlik/haftalik/oylik: tur nomi bo'yicha necha marta chiqilgan, daromad, xarajat, foyda/zarar."""
    start, end = period_range(period, anchor or today_local())
    rows = (await db.execute(
        select(
            Tour.title, func.count(Tour.id), func.sum(Tour.total_price),
            func.sum(Tour.platform_fee), func.sum(Tour.guide_cost),
            func.sum(Tour.driver_cost), func.sum(Tour.admin_cost), func.sum(Tour.profit),
        ).where(Tour.boss_id == user.id, Tour.status == TourStatus.completed,
                Tour.start_at >= start, Tour.start_at < end).group_by(Tour.title).order_by(func.sum(Tour.profit).desc())
    )).all()
    tours, totals = [], dict(runs=0, revenue=0, expenses=0, profit=0)
    for title, n, rev, pf, gc, dc, ac, pr in rows:
        exp = (pf or 0) + (gc or 0) + (dc or 0) + (ac or 0)
        tours.append(dict(title=title, runs=n, revenue=rev or 0, expenses=exp, profit=pr or 0,
                          result="foyda" if (pr or 0) >= 0 else "zarar"))
        totals["runs"] += n; totals["revenue"] += rev or 0; totals["expenses"] += exp; totals["profit"] += pr or 0
    rate = await get_usd_rate(db)
    totals_usd = {k: round(v / rate, 2) for k, v in totals.items() if k != "runs"}
    return {"period": period, "from": start, "to": end, "tours": tours, "totals": totals,
            "usd_rate": rate, "totals_usd": totals_usd}


@router.get("/boss/balance")
async def balance(user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    """cash_balance: platforma ulushi ayrilgan tushum minus allaqachon to'langan haqlar.
    free_balance: cash_balance minus hali to'lanmagan haqlar (jarimalar hisobga olingan)."""
    done = (Tour.boss_id == user.id) & (Tour.status == TourStatus.completed)
    profit, revenue, platform = (await db.execute(select(
        func.coalesce(func.sum(Tour.profit), 0), func.coalesce(func.sum(Tour.total_price), 0),
        func.coalesce(func.sum(Tour.platform_fee), 0)).where(done))).one()
    paid = (await db.execute(select(func.coalesce(func.sum(Payment.net), 0)).where(Payment.boss_id == user.id))).scalar_one()
    owed_earn = (await db.execute(select(func.coalesce(func.sum(Earning.amount), 0)).where(
        Earning.boss_id == user.id, Earning.payment_id.is_(None)))).scalar_one()
    owed_fine = (await db.execute(select(func.coalesce(func.sum(Fine.amount), 0)).where(
        Fine.boss_id == user.id, Fine.payment_id.is_(None)))).scalar_one()
    cash = revenue - platform - paid
    obligations = owed_earn - owed_fine
    return {"total_profit": profit, "paid_out": paid, "unpaid_obligations": obligations,
            "cash_balance": cash, "free_balance": cash - obligations}


# ---------- haftalik to'lovlar ----------
async def _due(db, boss_id: int, until=None):
    eq = select(Earning).where(Earning.boss_id == boss_id, Earning.payment_id.is_(None))
    fq = select(Fine).where(Fine.boss_id == boss_id, Fine.payment_id.is_(None))
    if until:
        eq = eq.where(Earning.created_at < until)
        fq = fq.where(Fine.created_at < until)
    return (await db.execute(eq)).scalars().all(), (await db.execute(fq)).scalars().all()


@router.get("/boss/payouts/due")
async def payouts_due(until: date | None = None, user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    """To'lanadigan odamlar: ism, nechta tur, jami summa (jarimalar ayrilgan). Admin haqi ham shu yerda."""
    until_dt = period_range("day", until)[1] if until else None
    earns, fines = await _due(db, user.id, until_dt)
    agg: dict[int, dict] = {}
    for e in earns:
        a = agg.setdefault(e.user_id, dict(user_id=e.user_id, tours=set(), gross=0, fines=0, kind=e.kind.value))
        a["tours"].add(e.tour_id); a["gross"] += e.amount
    for f in fines:
        a = agg.setdefault(f.user_id, dict(user_id=f.user_id, tours=set(), gross=0, fines=0, kind=None))
        a["fines"] += f.amount
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(agg)))).scalars().all()} if agg else {}
    out = []
    for uid, a in agg.items():
        u = users[uid]
        out.append(dict(user_id=uid, full_name=u.full_name, role=u.role.value, tours_count=len(a["tours"]),
                        gross=a["gross"], fines=a["fines"], net=a["gross"] - a["fines"]))
    out.sort(key=lambda x: (x["role"], x["full_name"]))
    return out


class PayIn(BaseModel):
    user_id: int
    until: date | None = None


@router.post("/boss/payouts/pay", status_code=201)
async def pay(data: PayIn, user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    """«To'ladim» — to'lov yaratiladi, oluvchiga xabar boradi, u tasdiqlaydi."""
    until_dt = period_range("day", data.until)[1] if data.until else None
    earns, fines = await _due(db, user.id, until_dt)
    earns = [e for e in earns if e.user_id == data.user_id]
    fines = [f for f in fines if f.user_id == data.user_id]
    if not earns and not fines:
        raise HTTPException(404, "Bu odamga to'lanadigan summa yo'q")
    gross, ftotal = sum(e.amount for e in earns), sum(f.amount for f in fines)
    p = Payment(boss_id=user.id, user_id=data.user_id, tours_count=len({e.tour_id for e in earns}),
                gross=gross, fines_total=ftotal, net=gross - ftotal)
    db.add(p)
    await db.flush()
    for e in earns: e.payment_id = p.id
    for f in fines: f.payment_id = p.id
    await notify(db, [data.user_id], f"Boshliq {user.full_name} sizga {p.net:,} so'm to'lov qildi. "
                 f"Olganingizni tasdiqlang.", user.id)
    await db.commit()
    return {"payment_id": p.id, "net": p.net, "status": p.status.value}


@router.get("/boss/payouts")
async def payout_history(user: User = Depends(boss_only), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Payment).where(Payment.boss_id == user.id).order_by(Payment.id.desc()))).scalars().all()
    return [dict(id=p.id, user_id=p.user_id, full_name=p.user.full_name, tours_count=p.tours_count, gross=p.gross,
                 fines=p.fines_total, net=p.net, status=p.status.value, created_at=p.created_at,
                 confirmed_at=p.confirmed_at) for p in rows]


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(payment_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Gid/haydovchi/admin o'ziga to'lov kelganini tasdiqlaydi."""
    p = await db.get(Payment, payment_id)
    if p is None or p.user_id != user.id:
        raise HTTPException(404, "To'lov topilmadi")
    if p.status == PayStatus.confirmed:
        raise HTTPException(409, "Allaqachon tasdiqlangan")
    p.status, p.confirmed_at = PayStatus.confirmed, now()
    await notify(db, [p.boss_id], f"{user.full_name} {p.net:,} so'm to'lovni oldim deb tasdiqladi.", user.id)
    await db.commit()
    return {"ok": True}


# ---------- shaxsiy hisob (gid, haydovchi, admin) ----------
@router.get("/me/account")
async def my_account(user: User = Depends(require_roles(Role.guide, Role.driver, Role.admin)),
                     db: AsyncSession = Depends(get_db)):
    unpaid = (await db.execute(select(func.coalesce(func.sum(Earning.amount), 0)).where(
        Earning.user_id == user.id, Earning.payment_id.is_(None)))).scalar_one()
    fines = (await db.execute(select(func.coalesce(func.sum(Fine.amount), 0)).where(
        Fine.user_id == user.id, Fine.payment_id.is_(None)))).scalar_one()
    pays = (await db.execute(select(Payment).where(Payment.user_id == user.id).order_by(Payment.id.desc()))).scalars().all()
    from app.services.common import driver_rating
    return {
        "unpaid_earnings": unpaid, "unpaid_fines": fines, "to_receive": unpaid - fines,
        "payments": [dict(id=p.id, net=p.net, status=p.status.value, created_at=p.created_at) for p in pays],
        "rating": await driver_rating(db, user.id) if user.role == Role.driver else None,
        "guide": ({"level": user.guide_profile.level, "level_tours": user.guide_profile.level_tours,
                   "completed_tours": user.guide_profile.completed_tours,
                   "practice_done": user.guide_profile.practice_done,
                   "interview_passed": user.guide_profile.interview_passed}
                  if user.role == Role.guide else None),
    }
