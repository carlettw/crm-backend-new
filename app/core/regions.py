# O'zbekiston viloyatlari (kod -> nom). Frontend'da ham shu ro'yxat (app.js: REGIONS) ishlatiladi.
REGIONS = {
    "tashkent_city": "Toshkent shahri", "tashkent": "Toshkent viloyati", "samarkand": "Samarqand",
    "bukhara": "Buxoro", "khorezm": "Xorazm", "navoi": "Navoiy", "kashkadarya": "Qashqadaryo",
    "surkhandarya": "Surxondaryo", "fergana": "Farg'ona", "andijan": "Andijon", "namangan": "Namangan",
    "syrdarya": "Sirdaryo", "jizzakh": "Jizzax", "karakalpakstan": "Qoraqalpog'iston",
}


def clean_regions(codes) -> list[str]:
    out: list[str] = []
    for c in codes or []:
        c = str(c).strip().lower()
        if c not in REGIONS:
            raise ValueError(f"Noma'lum viloyat: {c}")
        if c not in out:
            out.append(c)
    return out
