"""Telegram bot: webhook orqali ulanish va xabarlarni navbat (outbox) orqali yuborish."""
import asyncio
import hashlib
import logging

import httpx
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.timeutil import now
from app.db.session import SessionLocal
from app.models import Message, User

log = logging.getLogger("telegram")
ROLE_LABEL = {"super_admin": "Super admin", "boss": "Boshliq", "admin": "Admin", "guide": "Gid", "driver": "Haydovchi"}
state = {"error": None, "webhook": None}
_username: str | None = settings.telegram_bot_username or None


def enabled() -> bool:
    return bool(settings.telegram_bot_token)


def webhook_secret() -> str:
    return hashlib.sha256((settings.secret_key + ":tg").encode()).hexdigest()[:40]


async def tg_call(method: str, **params):
    """Telegram Bot API so'rovi. (HTTP status, javob JSON) qaytaradi."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}", json=params)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"ok": False, "description": r.text[:200]}


async def bot_username() -> str | None:
    global _username
    if _username:
        return _username
    if not enabled():
        return None
    try:
        _, d = await tg_call("getMe")
        if d.get("ok"):
            _username = d["result"]["username"]
    except Exception as e:  # noqa: BLE001
        log.warning("getMe xato: %s", e)
    return _username


async def setup():
    """Server ishga tushganda: bot nomini olish va webhook'ni o'rnatish."""
    try:
        if not await bot_username():
            state["error"] = "getMe ishlamadi: token noto'g'ri bo'lishi mumkin"
            return
        base = (settings.public_url or settings.render_external_url).rstrip("/")
        if not base:
            state["error"] = "PUBLIC_URL / RENDER_EXTERNAL_URL yo'q: webhook o'rnatilmadi"
            return
        url = f"{base}/api/v1/telegram/webhook"
        _, d = await tg_call("setWebhook", url=url, secret_token=webhook_secret(), allowed_updates=["message"])
        if d.get("ok"):
            state["webhook"], state["error"] = url, None
        else:
            state["error"] = f"setWebhook: {d.get('description')}"
        log.info("Telegram webhook: %s", state)
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)
        log.exception("Telegram setup xato")


def _format(m: Message, u: User, multi: bool) -> str:
    head = f"👤 {u.full_name} · {ROLE_LABEL.get(u.role.value, u.role.value)}\n" if multi else ""
    body = f"✉️ {m.sender_name}\n{m.body}" if m.sender_id else f"🔔 {m.body}"
    return head + body


async def send_pending() -> int:
    """Hali Telegramga yuborilmagan xabarlarni yuboradi (faqat ulangandan keyingilarini)."""
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Message, User).join(User, User.id == Message.recipient_id).where(
                User.telegram_chat_id.is_not(None), Message.tg_sent_at.is_(None),
                Message.created_at >= User.telegram_linked_at).order_by(Message.id).limit(25))).all()
        if not rows:
            return 0
        chats = {u.telegram_chat_id for _, u in rows}
        counts = dict((await db.execute(select(User.telegram_chat_id, func.count()).where(
            User.telegram_chat_id.in_(chats)).group_by(User.telegram_chat_id))).all())
        markup = {"inline_keyboard": [[{"text": "🌐 Saytni ochish", "url": settings.frontend_url}]]} if settings.frontend_url else None
        for m, u in rows:
            params = dict(chat_id=u.telegram_chat_id, text=_format(m, u, counts.get(u.telegram_chat_id, 1) > 1),
                          disable_web_page_preview=True)
            if markup:
                params["reply_markup"] = markup
            try:
                status, d = await tg_call("sendMessage", **params)
            except Exception as e:  # noqa: BLE001
                log.warning("Telegram yuborilmadi: %s", e)
                status, d = 0, {"ok": False}
            if d.get("ok"):
                m.tg_sent_at = now()
            elif status in (400, 403) and any(k in str(d.get("description", "")).lower() for k in ("blocked", "chat not found", "deactivated", "kicked")):
                # foydalanuvchi botni bloklagan: ulanish uziladi
                await db.execute(update(User).where(User.telegram_chat_id == u.telegram_chat_id).values(telegram_chat_id=None, telegram_linked_at=None))
                m.tg_sent_at = now()
            elif status == 429:
                await db.commit()
                await asyncio.sleep(float(d.get("parameters", {}).get("retry_after", 2)) + 1)
                return len(rows)
            else:
                m.tg_tries = (m.tg_tries or 0) + 1
                if m.tg_tries >= 5:
                    m.tg_sent_at = now()  # 5 marta urinib bo'lmadi: tashlab ketamiz
            await asyncio.sleep(0.05)
        await db.commit()
        return len(rows)


async def sender_loop():
    while True:
        n = 0
        try:
            n = await send_pending()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Telegram yuborish sikli xato")
        await asyncio.sleep(0.5 if n else settings.telegram_poll_seconds)
