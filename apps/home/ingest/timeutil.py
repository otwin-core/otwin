"""Local Spanish time to UTC, without losing or inventing an hour.

Spanish files write local time. Twice a year a local day is not 24 hours
long: the last Sunday of March has 23 and the last Sunday of October has 25,
with 02:00-03:00 repeated. Everything here works in whole UTC seconds, and
refuses a local time that never happened rather than guessing.

Peninsular Spain and the Balearic Islands are ``Europe/Madrid``. The Canary
Islands are ``Atlantic/Canary``, one hour behind. Ceuta and Melilla follow
``Europe/Madrid``.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

__all__ = [
    "DEFAULT_TZ",
    "zone",
    "local_to_utc",
    "is_ambiguous",
    "midnight_utc",
    "day_hours",
    "parse_date",
    "parse_datetime",
    "parse_year_month",
    "FoldTracker",
    "utc_seconds",
]

DEFAULT_TZ = "Europe/Madrid"


def zone(name: str) -> ZoneInfo:
    """The time zone called ``name`` (IANA), with a clear error if unknown."""
    try:
        return ZoneInfo(name)
    except Exception as exc:  # ZoneInfoNotFoundError, ValueError
        raise ValueError(f"unknown time zone {name!r}") from exc


def local_to_utc(naive: datetime, tz: ZoneInfo, fold: int = 0) -> int:
    """UTC seconds of a local wall-clock time.

    ``fold`` picks the second occurrence of a repeated hour (October).
    Raises ``ValueError`` for a time skipped by the March change.
    """
    aware = naive.replace(tzinfo=tz, fold=fold)
    ts = int(aware.timestamp())
    back = datetime.fromtimestamp(ts, tz).replace(tzinfo=None)
    if back != naive.replace(microsecond=0):
        raise ValueError(
            f"{naive:%Y-%m-%d %H:%M} never happened in {tz.key}: the clocks went "
            "forward over it"
        )
    return ts


def is_ambiguous(naive: datetime, tz: ZoneInfo) -> bool:
    """True if this wall-clock time happened twice (the October change)."""
    a = naive.replace(tzinfo=tz, fold=0).timestamp()
    b = naive.replace(tzinfo=tz, fold=1).timestamp()
    return a != b


def midnight_utc(day: date, tz: ZoneInfo) -> int:
    """UTC seconds of the local midnight that starts ``day``."""
    return local_to_utc(datetime(day.year, day.month, day.day), tz)


def day_hours(day: date, tz: ZoneInfo) -> int:
    """How many hours the local day has: 23, 24 or 25."""
    return (midnight_utc(day + timedelta(days=1), tz) - midnight_utc(day, tz)) // 3600


_DATE = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})")
_DATETIME = re.compile(
    r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})"
    r"(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?$"
)
_YEAR_MONTH = re.compile(r"^(\d{4})[/\-.](\d{1,2})$")


def _ymd(a: str, b: str, c: str, text: str) -> date:
    if len(a) == 4:
        y, m, d = int(a), int(b), int(c)
    elif len(c) == 4:
        d, m, y = int(a), int(b), int(c)
    else:
        raise ValueError(f"{text!r}: the year must have four digits")
    try:
        return date(y, m, d)
    except ValueError:
        raise ValueError(f"{text!r} is not a valid date") from None


def parse_date(text: str) -> date:
    """``dd/mm/yyyy``, ``yyyy/mm/dd``, ``yyyy-mm-dd``, ``dd.mm.yyyy``, ``dd-mm-yyyy``.

    Day-first versus year-first is decided by where the four-digit year is;
    ``mm/dd/yyyy`` is not a Spanish format and is not accepted.

    >>> parse_date("06/09/2015"), parse_date("2015/09/06")
    (datetime.date(2015, 9, 6), datetime.date(2015, 9, 6))
    """
    t = text.strip()
    m = _DATE.match(t)
    if not m or t[m.end() :].strip():
        raise ValueError(f"{text!r} is not a date")
    return _ymd(*m.groups(), text=text)


def parse_datetime(text: str) -> tuple[datetime, bool]:
    """A date with an optional time, and whether it was given in UTC.

    Returns ``(naive_datetime, is_utc)``. An ISO offset (``Z``, ``+01:00``) is
    applied and the result is naive UTC with ``is_utc=True``. Without an
    offset the result is local wall-clock time with ``is_utc=False``. ``24:00``
    is read as midnight at the end of the day.

    >>> parse_datetime("2020/09/01 01:00")
    (datetime.datetime(2020, 9, 1, 1, 0), False)
    >>> parse_datetime("2024-02-07T10:00:00.000Z")
    (datetime.datetime(2024, 2, 7, 10, 0), True)
    """
    t = text.strip()
    m = _DATETIME.match(t)
    if not m:
        raise ValueError(f"{text!r} is not a date and time")
    a, b, c, hh, mm, ss, off = m.groups()
    d = _ymd(a, b, c, text)
    h, mi, s = int(hh or 0), int(mm or 0), int(ss or 0)
    if h == 24 and mi == 0 and s == 0:
        naive = datetime(d.year, d.month, d.day) + timedelta(days=1)
    elif h > 23 or mi > 59 or s > 59:
        raise ValueError(f"{text!r} has an invalid time of day")
    else:
        naive = datetime(d.year, d.month, d.day, h, mi, s)
    if off is None:
        return naive, False
    if off == "Z":
        return naive, True
    sign = 1 if off[0] == "+" else -1
    digits = off[1:].replace(":", "")
    delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
    return naive - sign * delta, True


def parse_year_month(text: str) -> tuple[int, int]:
    """``yyyy/mm`` or ``yyyy-mm`` as ``(year, month)``."""
    m = _YEAR_MONTH.match(text.strip())
    if not m:
        raise ValueError(f"{text!r} is not a year and month")
    y, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12:
        raise ValueError(f"{text!r} has an invalid month")
    return y, mo


def utc_seconds(naive_utc: datetime) -> int:
    """UTC seconds of a naive datetime that is already in UTC."""
    return int(naive_utc.replace(tzinfo=timezone.utc).timestamp())


class FoldTracker:
    """Resolve repeated local times in file order.

    A file that labels each hour by its local wall-clock time writes
    ``02:00`` twice on the October change day. The first occurrence is
    summer time and the second winter time. ``utc(naive)`` returns the right
    one for each, and refuses a third occurrence or a time that never
    happened.
    """

    def __init__(self, tz: ZoneInfo) -> None:
        self.tz = tz
        self.seen: Counter[datetime] = Counter()

    def utc(self, naive: datetime) -> int:
        """UTC seconds for ``naive``, the second time it appears taken as fold 1."""
        k = self.seen[naive]
        self.seen[naive] += 1
        if k == 0:
            return local_to_utc(naive, self.tz)
        if k == 1 and is_ambiguous(naive, self.tz):
            return local_to_utc(naive, self.tz, fold=1)
        raise ValueError(f"{naive:%Y-%m-%d %H:%M} appears more than once")
