"""Dushanba kuni boshliqlarga haftalik to'lov eslatmasi (soat 09:00 Toshkent)."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.core.timeutil import TZ, today_local
from app.db.session import SessionLocal
from app.models import AppSetting, Role, User
from app.services.common import notify
from app.services.payouts import default_cutoff, due_items

log = logging.getLogger("weekly")
KEY = "last_weekly_reminder"


async def send_weekly_reminders(db, force: bool = False) -> int:
    today = today_local()
    if not force and (today.weekday() != 0 or datetime.now(TZ).hour < 9):
        return 0
    row = await db.get(AppSetting, KEY)
    if not force and row and row.value == today.isoformat():
        return 0
    sent = 0
    bosses = (await db.execute(select(User).where(User.role == Role.boss, User.is_active.is_(True)))).scalars().all()
    for b in bosses:
        items = await due_items(db, b.id, default_cutoff())
        if not items:
            continue
        total = sum(i["net"] for i in items)
        no_card = [i["full_name"] for i in items if not i["card"]]
        msg = (f"📅 Bugun dushanba: haftalik to'lov kuni.\n{len(items)} kishiga jami {total:,} so'm to'lanadi."
               + (f"\n⚠️ Karta kiritmaganlar: {', '.join(no_card)}." if no_card else "")
               + "\n«To'lovlar» bo'limiga kiring.")
        await notify(db, [b.id], msg)
        sent += 1
    if row:
        row.value = today.isoformat()
    else:
        db.add(AppSetting(key=KEY, value=today.isoformat()))
    await db.commit()
    return sent


async def weekly_loop():
    while True:
        try:
            async with SessionLocal() as db:
                await send_weekly_reminders(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Haftalik eslatma xato")
        await asyncio.sleep(600)
