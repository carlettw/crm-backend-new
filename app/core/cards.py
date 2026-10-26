import re


def normalize(number: str) -> str:
    return re.sub(r"[\s\-]", "", number or "")


def luhn_ok(n: str) -> bool:
    total, alt = 0, False
    for ch in reversed(n):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def validate(number: str) -> str:
    n = normalize(number)
    if not re.fullmatch(r"\d{16}", n):
        raise ValueError("Karta raqami 16 ta raqamdan iborat bo'lishi kerak")
    if not luhn_ok(n):
        raise ValueError("Karta raqami noto'g'ri (raqamlarni qayta tekshiring)")
    return n


def brand(n: str | None) -> str | None:
    if not n:
        return None
    if n.startswith("8600"):
        return "Uzcard"
    if n.startswith("9860"):
        return "Humo"
    if n.startswith("4"):
        return "Visa"
    if n[:2] in ("51", "52", "53", "54", "55"):
        return "Mastercard"
    return "Karta"


def mask(n: str | None) -> str | None:
    return f"{n[:4]} **** **** {n[-4:]}" if n else None


def pretty(n: str | None) -> str | None:
    return " ".join(n[i:i + 4] for i in range(0, 16, 4)) if n else None
