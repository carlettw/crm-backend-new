# Tillar ro'yxati (kod -> o'zbekcha nom). Frontend'da ham shu ro'yxat (app.js: LANGS) ishlatiladi.
LANGUAGES = {
    "uz": "O'zbek", "ru": "Rus", "en": "Ingliz", "de": "Nemis", "fr": "Frantsuz", "es": "Ispan",
    "it": "Italyan", "pt": "Portugal", "zh": "Xitoy", "ja": "Yapon", "ko": "Koreys", "tr": "Turk",
    "ar": "Arab", "fa": "Fors", "hi": "Hind", "kk": "Qozoq",
}


def clean_languages(codes) -> list[str]:
    out: list[str] = []
    for c in codes or []:
        c = str(c).strip().lower()
        if c not in LANGUAGES:
            raise ValueError(f"Noma'lum til: {c}")
        if c not in out:
            out.append(c)
    return out
