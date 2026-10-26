"""Haftalik to'lovlar: dushanba hisobi, to'lanmagan haqlar va jarimalar."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cards
from app.core.timeutil import period_range, today_local
from app.models import Earning, Fine, User


def default_cutoff():
    """Joriy haftaning dushanba 00:00 (Toshkent): shundan oldingi haqlar to'lanadi."""
    return period_range("week", today_local())[0]


def next_pay_day() -> date:
    d = today_local()
    return d if d.weekday() == 0 else d + timedelta(days=7 - d.weekday())


def resolve_cutoff(until: date | None, all_: bool):
    if all_:
        return None
    if until:
        return period_range("day", until)[1]
    return default_cutoff()


async def due_rows(db: AsyncSession, boss_id: int, cutoff=None):
    eq = select(Earning).where(Earning.boss_id == boss_id, Earning.payment_id.is_(None))
    fq = select(Fine).where(Fine.boss_id == boss_id, Fine.payment_id.is_(None))
    if cutoff:
        eq = eq.where(Earning.created_at < cutoff)
        fq = fq.where(Fine.created_at < cutoff)
    return (await db.execute(eq)).scalars().all(), (await db.execute(fq)).scalars().all()


async def due_items(db: AsyncSession, boss_id: int, cutoff=None) -> list[dict]:
    earns, fines = await due_rows(db, boss_id, cutoff)
    agg: dict[int, dict] = {}
    for e in earns:
        a = agg.setdefault(e.user_id, dict(tours=set(), gross=0, fines=0))
        a["tours"].add(e.tour_id)
        a["gross"] += e.amount
    for f in fines:
        a = agg.setdefault(f.user_id, dict(tours=set(), gross=0, fines=0))
        a["fines"] += f.amount
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(agg)))).scalars().all()} if agg else {}
    out = []
    for uid, a in agg.items():
        u = users[uid]
        card = None
        if u.card_number:  # to'liq raqam faqat to'lov qiluvchi boshliqqa ko'rinadi
            card = {"number": u.card_number, "formatted": cards.pretty(u.card_number),
                    "brand": cards.brand(u.card_number), "holder": u.card_holder}
        out.append(dict(user_id=uid, full_name=u.full_name, role=u.role.value, tours_count=len(a["tours"]),
                        gross=a["gross"], fines=a["fines"], net=a["gross"] - a["fines"], card=card))
    out.sort(key=lambda x: (x["role"], x["full_name"]))
    return out
