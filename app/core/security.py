import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# ---------- JWT ----------
# "ver" = foydalanuvchining token_version qiymati. Parol o'zgarganda / tiklanganda / "hamma qurilmalardan chiqish"da
# token_version oshiriladi va eski tokenlar yaroqsiz bo'ladi.
def _make_token(user_id: int, token_type: str, delta: timedelta, version: int) -> str:
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "ver": version,
        "exp": datetime.now(timezone.utc) + delta,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(user_id: int, version: int = 0) -> str:
    return _make_token(user_id, "access", timedelta(minutes=settings.access_token_minutes), version)


def create_refresh_token(user_id: int, version: int = 0) -> str:
    return _make_token(user_id, "refresh", timedelta(days=settings.refresh_token_days), version)


def decode_token(token: str, expected_type: str) -> tuple[int, int] | None:
    """(user_id, token_version) yoki None."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return int(payload["sub"]), int(payload.get("ver", 0))
    except (KeyError, TypeError, ValueError):
        return None


# ---------- karta raqamini shifrlash ----------
from app.core.config import DEFAULT_SECRET  # noqa: E402


def _key(raw: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def _primary_raw() -> str:
    return settings.card_encryption_key or ("card:" + settings.secret_key)


def _old_raws() -> list[str]:
    """Eski kalitlar: faqat o'qish uchun (yozuvlar ishga tushishda yangi kalitga o'tkaziladi).
    Standart "change-me" dan hosil bo'lgan kalit doim shu ro'yxatda — SECRET_KEY qo'yilmagan holda
    shifrlangan kartalar yangi kalit qo'yilganda yo'qolmasin."""
    olds = [k.strip() for k in settings.card_old_keys.split(",") if k.strip()]
    olds.append("card:" + DEFAULT_SECRET)
    return [k for k in dict.fromkeys(olds) if k != _primary_raw()]


def _fernet() -> MultiFernet:
    return MultiFernet([_key(_primary_raw())] + [_key(k) for k in _old_raws()])


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str | None:
    if value is None:
        return None
    if value.isdigit():  # eski (shifrlanmagan) yozuv
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def needs_rekey(value: str | None) -> bool:
    """Yozuv joriy kalit bilan emas (eski kalit yoki shifrlanmagan) — qayta shifrlash kerak."""
    if not value:
        return False
    if value.isdigit():
        return True
    try:
        _key(_primary_raw()).decrypt(value.encode())
        return False
    except InvalidToken:
        return decrypt_str(value) is not None


def derived_secret(purpose: str) -> str:
    return hmac.new(settings.secret_key.encode(), purpose.encode(), hashlib.sha256).hexdigest()[:40]


# ---------- login urinishlarini cheklash ----------
class LoginLimiter:
    """Xotirada: kalit (username yoki IP) bo'yicha muvaffaqiyatsiz urinishlar.
    Bitta server nusxasi uchun yetarli; bir nechta nusxada har biri o'z hisobini yuritadi."""

    def __init__(self, factor: int = 1):
        self.factor = factor  # IP uchun limit kattaroq (bitta ofisdan ko'p odam kirishi mumkin)
        self.fails: dict[str, deque] = defaultdict(deque)

    def _window(self) -> float:
        return settings.login_lock_minutes * 60

    def _prune(self, key: str, t: float):
        q = self.fails[key]
        while q and t - q[0] > self._window():
            q.popleft()
        if not q:
            self.fails.pop(key, None)

    def retry_after(self, *keys: str) -> int:
        t = time.monotonic()
        worst = 0
        for k in keys:
            self._prune(k, t)
            q = self.fails.get(k)
            if q and len(q) >= settings.login_max_attempts * self.factor:
                worst = max(worst, int(self._window() - (t - q[0])) + 1)
        return worst

    def fail(self, *keys: str):
        t = time.monotonic()
        for k in keys:
            self.fails[k].append(t)

    def reset(self, *keys: str):
        for k in keys:
            self.fails.pop(k, None)


user_limiter = LoginLimiter()
ip_limiter = LoginLimiter(factor=4)
