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
        "id": t.id, "title": t.title, "language": t.language, "languages": t.languages, "region": t.region, "needs_driver": t.needs_driver, "description": t.description, "status": t.status.value,
        "start_at": t.start_at, "pickup_address": t.pickup_address,
        "stops": [{"address": s.address, "duration_minutes": s.duration_minutes, "description": s.description,
                   "location_url": s.location_url, "arrival_time": s.arrival_time} for s in t.stops],
        "amount": amount, "note": note, "pax_count": t.pax_count,
        "urgent": t.urgent, "hours_left": t.hours_left,
        "guide_confirmed": bool(t.guide_confirmed_at), "driver_confirmed": bool(t.driver_confirmed_at),
    }
    # turist guruhlari: til + odam soni hammaga; ism/aloqa faqat gid tur qabul qilgach
    v["groups"] = [dict(language=g.language, pax_count=g.pax_count,
                        **(dict(tourist_name=g.tourist_name, tourist_phone=g.tourist_phone,
                                tourist_email=g.tourist_email, messenger=g.messenger)
                           if role == "guide" and detail else {})) for g in t.groups]
    return v
