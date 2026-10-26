import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.core.timeutil import aware, now
from app.db.session import get_db
from app.models import Role, User
from app.services import telegram as tg

router = APIRouter(tags=["telegram"])

HELP = ("Salom! Bu Tur Boshqaruv boti.\n\n"
        "Hisobingizni ulash uchun saytda «📲 Telegramni ulash» tugmasini bosing, shundan keyin shu botga qaytib «Start» ni bosing.\n\n"
        "Buyruqlar:\n/status — ulangan hisoblar\n/stop — Telegramni uzish")


async def _say(chat_id: int, text: str):
    try:
        await tg.tg_call("sendMessage", chat_id=chat_id, text=text)
    except Exception:  # noqa: BLE001
        pass


@router.post("/telegram/webhook", include_in_schema=False)
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != tg.webhook_secret():
        raise HTTPException(403, "Ruxsat yo'q")
    upd = await request.json()
    msg = upd.get("message") or {}
    chat = msg.get("chat") or {}
    text = (msg.get("text") or "").strip()
    chat_id = chat.get("id")
    if not chat_id or not text or chat.get("type") != "private":
        return {"ok": True}
    cmd, _, arg = text.partition(" ")
    cmd, arg = cmd.split("@")[0].lower(), arg.strip()

    if cmd == "/start" and arg:
        u = (await db.execute(select(User).where(User.tg_link_code == arg))).scalar_one_or_none()
        if u is None or u.tg_link_expires is None or aware(u.tg_link_expires) < now() or not u.is_active:
            await _say(chat_id, "❌ Kod yaroqsiz yoki muddati tugagan. Saytda «Telegramni ulash» tugmasini qayta bosing.")
        else:
            u.telegram_chat_id, u.telegram_linked_at = chat_id, now()
            u.tg_link_code = u.tg_link_expires = None
            await db.commit()
            await _say(chat_id, f"✅ Ulandi: {u.full_name} ({tg.ROLE_LABEL.get(u.role.value)}).\n"
                                "Endi barcha bildirishnomalar shu yerga ham keladi.\nUzish: /stop")
    elif cmd in ("/stop", "/uzish"):
        await db.execute(update(User).where(User.telegram_chat_id == chat_id).values(telegram_chat_id=None, telegram_linked_at=None))
        await db.commit()
        await _say(chat_id, "Telegram uzildi. Qayta ulash uchun saytdagi «Telegramni ulash» tugmasini bosing.")
    elif cmd == "/status":
        us = (await db.execute(select(User).where(User.telegram_chat_id == chat_id))).scalars().all()
        await _say(chat_id, "Ulangan hisoblar:\n" + "\n".join(f"• {u.full_name} — {tg.ROLE_LABEL.get(u.role.value)} (@{u.username})" for u in us)
                   if us else "Hech qanday hisob ulanmagan.\n\n" + HELP)
    else:
        await _say(chat_id, HELP)
    return {"ok": True}


@router.get("/me/telegram")
async def my_telegram(user: User = Depends(get_current_user)):
    return {"enabled": tg.enabled(), "linked": user.telegram_chat_id is not None}


@router.post("/me/telegram/link")
async def link(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Bir martalik kod yaratadi; foydalanuvchi havola orqali botda «Start» bosadi."""
    if not tg.enabled():
        raise HTTPException(503, "Telegram bot hali sozlanmagan")
    name = await tg.bot_username()
    if not name:
        raise HTTPException(503, "Telegram botga ulanib bo'lmadi, birozdan keyin qayta urinib ko'ring")
    user.tg_link_code = secrets.token_urlsafe(16)
    user.tg_link_expires = now() + timedelta(minutes=15)
    await db.commit()
    return {"url": f"https://t.me/{name}?start={user.tg_link_code}", "bot": name, "expires_in": 900}


@router.delete("/me/telegram", status_code=204)
async def unlink(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user.telegram_chat_id = user.telegram_linked_at = None
    await db.commit()


@router.get("/telegram/status")
async def status(_: User = Depends(require_roles(Role.super_admin))):
    """Super admin uchun diagnostika: bot sozlanganmi, webhook o'rnatilganmi."""
    out = {"configured": tg.enabled(), "bot": await tg.bot_username(), "webhook": tg.state["webhook"], "error": tg.state["error"]}
    if tg.enabled():
        try:
            _, d = await tg.tg_call("getWebhookInfo")
            r = d.get("result", {})
            out.update(telegram_webhook_url=r.get("url"), pending_updates=r.get("pending_update_count"),
                       last_error=r.get("last_error_message"))
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
    return out
