from app.models import Tour


def job_view(t: Tour, role: str, level: int | None = None, detail: bool = False) -> dict:
    """Gid/haydovchi uchun ko'rinish. Gid summasi 1-2 darajada 0 (tekin).
    Turist ma'lumotlari faqat gid tur qabul qilgach (detail) ko'rinadi. Umumiy aylanma ko'rinmaydi."""
    if role == "guide":
        amount = t.guide_amount if (level or 0) >= 3 else 0
        note = t.guide_note
    else:
        amount, note = t.driver_amount, t.driver_note
    v = {
        "id": t.id, "title": t.title, "description": t.description, "status": t.status.value,
        "start_at": t.start_at, "pickup_address": t.pickup_address,
        "stops": [{"address": s.address, "duration_minutes": s.duration_minutes, "description": s.description,
                   "location_url": s.location_url, "arrival_time": s.arrival_time} for s in t.stops],
        "amount": amount, "note": note, "pax_count": t.pax_count,
        "guide_confirmed": bool(t.guide_confirmed_at), "driver_confirmed": bool(t.driver_confirmed_at),
    }
    if role == "guide" and detail:
        v.update(tourist_name=t.tourist_name, tourist_phone=t.tourist_phone,
                 tourist_email=t.tourist_email, messenger=t.messenger)
    return v
