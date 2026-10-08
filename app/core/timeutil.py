from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
CANCEL_LIMIT = timedelta(hours=24)


def now() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    """Bazadan (SQLite) tz-siz qaytsa UTC deb hisoblaymiz."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def to_utc(dt: datetime) -> datetime:
    """Tz-siz kiritilsa Toshkent vaqti deb olinadi."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc)


def local_day_range(d: date, days: int = 1) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=TZ)
    end = start + timedelta(days=days)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def period_range(period: str, anchor: date) -> tuple[datetime, datetime]:
    if period == "day":
        return local_day_range(anchor, 1)
    if period == "week":
        return local_day_range(anchor - timedelta(days=anchor.weekday()), 7)
    first = anchor.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return local_day_range(first, (nxt - first).days)


def today_local() -> date:
    return datetime.now(TZ).date()
