import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.timezone)


def now_tw() -> datetime:
    return datetime.now(TZ)


def today_tw() -> date:
    return now_tw().date()


def roc_to_date(s: str) -> date | None:
    """'115/10/01' or '115/10/1' -> date(2026, 10, 1)."""
    if not s:
        return None
    m = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})\s*$", s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    return date(y + 1911, mo, d)


def roc_compact_to_date(s: str) -> date | None:
    """'1151029' -> date(2026, 10, 29)."""
    if not s or not s.strip().isdigit() or len(s.strip()) not in (6, 7):
        return None
    s = s.strip()
    y, mo, d = int(s[:-4]), int(s[-4:-2]), int(s[-2:])
    return date(y + 1911, mo, d)


def parse_date_any(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3 and len(parts[0]) == 4:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        return roc_to_date(s)
    if s.isdigit():
        if len(s) == 8:
            return date(int(s[:4]), int(s[4:6]), int(s[6:]))
        return roc_compact_to_date(s)
    if "-" in s:
        return date.fromisoformat(s)
    return None


def to_float(s) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").replace("+", "").strip()
    if s in ("", "-", "--", "---", "X", "除權息", "除權", "除息", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(s) -> int | None:
    f = to_float(s)
    return int(f) if f is not None else None


def yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def slash_date(d: date) -> str:
    return d.strftime("%Y/%m/%d")


def is_trading_hours(dt: datetime | None = None, pre: int = 5, post: int = 5) -> bool:
    """Weekday 09:00-13:30 (with a small margin). Holidays are not checked;
    the exchange simply returns no new data on those days."""
    dt = dt or now_tw()
    if dt.weekday() >= 5:
        return False
    minutes = dt.hour * 60 + dt.minute
    return (9 * 60 - pre) <= minutes <= (13 * 60 + 30 + post)
