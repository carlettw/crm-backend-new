"""Tashqi cron uchun endpoint (Render bepul tarifida server uxlab qolganda ham vazifalar bajarilishi uchun).

cron-job.org (yoki UptimeRobot) da har 10 daqiqada:
    GET https://<backend>/api/v1/cron/tick?key=<CRON_SECRET>
Bu serverni uyg'otadi, dushanba eslatmasini va Telegram navbatini ishlatadi.
"""
import hmac

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.security import derived_secret
from app.db.session import SessionLocal
from app.services import telegram as tg
from app.services import weekly

router = APIRouter(tags=["cron"])


def cron_key() -> str:
    return settings.cron_secret or derived_secret("cron")


@router.get("/cron/tick", include_in_schema=False)
async def tick(key: str = Query("")):
    if not hmac.compare_digest(key, cron_key()):
        raise HTTPException(403, "Kalit noto'g'ri")
    from sqlalchemy import text
    async with SessionLocal() as db:
        if "supabase" in settings.database_url:
            # Supabase bepul bazasi "faolsiz" deb to'xtab qolmasligi uchun.
            # Neon'da kerak emas (u loyihani to'xtatmaydi, faqat uxlaydi — uyg'otish bepul limitni sarflaydi).
            await db.execute(text("SELECT 1"))
        reminders = await weekly.send_weekly_reminders(db)
    sent = 0
    if tg.enabled():
        sent = await tg.send_pending()
    return {"ok": True, "weekly_reminders": reminders, "telegram_batch": sent}


from fastapi import Depends  # noqa: E402

from app.core.deps import require_roles  # noqa: E402
from app.models import Role, User  # noqa: E402


@router.get("/cron/info")
async def cron_info(_: User = Depends(require_roles(Role.super_admin))):
    """Super admin uchun: tashqi cron'ga qo'yiladigan manzil."""
    base = (settings.public_url or settings.render_external_url).rstrip("/")
    path = f"/api/v1/cron/tick?key={cron_key()}"
    return {"url": (base + path) if base else None, "path": path, "every_minutes": 10}
