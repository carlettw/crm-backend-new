"""Amaliyot (1-daraja) va sertifikat: 3 xil turdagi 3 ta turda amaliyot o'tgan gidga sertifikat beriladi."""
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.timeutil import TZ, aware
from app.models import AppKind, AppStatus, Certificate, GuideProfile, Tour, TourApplication, TourStatus, User

NEED_TYPES = 3
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # o'xshash belgilar (0/O, 1/I) yo'q


def norm_title(t: str) -> str:
    return " ".join((t or "").lower().split())


async def practice_progress(db: AsyncSession, user_id: int) -> dict:
    """Amaliyotchi qatnashgan YAKUNLANGAN turlar; «tur turi» = tur nomi (Buxoro city tour va h.k.)."""
    rows = (await db.execute(
        select(Tour.title, Tour.start_at).join(TourApplication, TourApplication.tour_id == Tour.id).where(
            TourApplication.user_id == user_id, TourApplication.kind == AppKind.practice,
            TourApplication.status == AppStatus.approved, Tour.status == TourStatus.completed
        ).order_by(Tour.start_at))).all()
    types: dict[str, dict] = {}
    for title, start in rows:
        types.setdefault(norm_title(title), {"title": title, "date": aware(start).astimezone(TZ).date().isoformat()})
    return {"types": len(types), "need": NEED_TYPES, "all_tours": len(rows), "tours": list(types.values())}


async def practice_counts(db: AsyncSession, user_ids: list[int]) -> dict[int, dict]:
    """Bir nechta amaliyotchi uchun bitta so'rovda: {user_id: {"types": .., "all_tours": ..}}."""
    if not user_ids:
        return {}
    rows = (await db.execute(
        select(TourApplication.user_id, Tour.title).join(Tour, TourApplication.tour_id == Tour.id).where(
            TourApplication.user_id.in_(user_ids), TourApplication.kind == AppKind.practice,
            TourApplication.status == AppStatus.approved, Tour.status == TourStatus.completed))).all()
    out = {u: {"types": set(), "all_tours": 0} for u in user_ids}
    for uid, title in rows:
        out[uid]["types"].add(norm_title(title))
        out[uid]["all_tours"] += 1
    return {u: {"types": len(v["types"]), "all_tours": v["all_tours"]} for u, v in out.items()}


async def _new_code(db: AsyncSession) -> str:
    while True:
        code = "TB-" + "".join(secrets.choice(ALPHABET) for _ in range(8))
        if (await db.execute(select(Certificate.id).where(Certificate.code == code))).first() is None:
            return code


async def maybe_issue(db: AsyncSession, user_id: int):
    """1-daraja gid 3 xil turda amaliyot o'tgan bo'lsa 2-darajaga o'tadi.
    Sertifikat faqat CERTIFICATES_ENABLED=true bo'lganda beriladi (hozircha o'chirilgan)."""
    from app.services.common import notify
    gp = (await db.execute(select(GuideProfile).where(GuideProfile.user_id == user_id))).scalar_one_or_none()
    if gp is None or gp.level != 1:
        return None
    prog = await practice_progress(db, user_id)
    if prog["types"] < NEED_TYPES:
        return None
    gp.level, gp.level_tours = 2, 0
    if not settings.certificates_enabled:
        await notify(db, [user_id], "Tabriklaymiz! Amaliyotni muvaffaqiyatli tugatdingiz (3 xil turdagi 3 ta tur). Siz 2-darajaga ko'tarildingiz.")
        return None
    if (await db.execute(select(Certificate.id).where(Certificate.user_id == user_id))).first():
        return None
    user = await db.get(User, user_id)
    cert = Certificate(code=await _new_code(db), user_id=user_id, holder_name=user.full_name, tours=prog["tours"][:NEED_TYPES])
    db.add(cert)
    await notify(db, [user_id], f"Tabriklaymiz! Amaliyotni muvaffaqiyatli tugatdingiz. Sertifikat kodi: {cert.code}. "
                                "Siz 2-darajaga ko'tarildingiz. Sertifikatni «Darajam» bo'limida ko'rasiz.")
    return cert
