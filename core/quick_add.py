"""Parse quick-add text like "gym tomorrow 5pm" or "dentist fri 2:30-3:30pm" into one event, without the model.

Recognizes: today / tonight / tomorrow, weekdays ("fri", "next mon"), dates ("9/20", "sep 25",
"2026-09-20"), times ("5pm", "17:00", "noon"), ranges ("2-3:30pm", "10am to 2pm"), and durations
("for 2h", "for 45 min"). Whatever is left becomes the title.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

DEFAULT_MINUTES = 60
TONIGHT_DEFAULT = time(20, 0)
WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "weds": 2, "wed": 2,
    "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
CONNECTORS = r"at|on|from|to|for|by|this|next"

_AMPM = r"[ap]\.?m\.?(?![a-z])"
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY_NAMES = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_FLAGS = re.IGNORECASE

_DURATION_RE = re.compile(r"\bfor\s+(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>h|hrs?|hours?|m|mins?|minutes?)\b", _FLAGS)
_ISO_RE = re.compile(r"(?:\bon\s+)?\b(?P<y>\d{4})-(?P<mo>\d{1,2})-(?P<d>\d{1,2})\b", _FLAGS)
_SLASH_RE = re.compile(r"(?:\bon\s+)?\b(?P<mo>\d{1,2})/(?P<d>\d{1,2})(?:/(?P<y>\d{2}|\d{4}))?\b", _FLAGS)
_MONTH_DAY_RE = re.compile(rf"(?:\bon\s+)?\b(?P<mon>{_MONTH_NAMES})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b", _FLAGS)
_DAY_MONTH_RE = re.compile(rf"(?:\bon\s+)?\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mon>{_MONTH_NAMES})\b", _FLAGS)
_RELATIVE_RE = re.compile(r"(?:\bon\s+)?\b(?P<word>today|tonight|tomorrow|tmrw|tmr)\b", _FLAGS)
_WEEKDAY_RE = re.compile(rf"(?:\bon\s+)?\b(?:(?P<next>next)\s+|this\s+)?(?P<wd>{_WEEKDAY_NAMES})\b", _FLAGS)
_RANGE_RE = re.compile(
    rf"(?:\bfrom\s+)?\b(?P<h1>\d{{1,2}})(?::(?P<m1>[0-5]\d))?\s*(?P<ap1>{_AMPM})?\s*"
    rf"(?:-|–|—|\bto\b|\buntil\b|\btill\b)\s*"
    rf"(?P<h2>\d{{1,2}})(?::(?P<m2>[0-5]\d))?\s*(?P<ap2>{_AMPM})?(?![\w:])",
    _FLAGS,
)
_TIME_RE = re.compile(
    rf"(?:\bat\s+)?(?:\b(?P<h>\d{{1,2}})(?::(?P<m>[0-5]\d))?\s*(?P<ap>{_AMPM})"
    rf"|\b(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)(?![\w:])"
    rf"|\b(?P<word>noon|midday)\b)",
    _FLAGS,
)


def _clock(hour_text: str, minute_text: str | None, ampm: str | None) -> time | None:
    hour, minute = int(hour_text), int(minute_text or 0)
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm[0].lower() == "p" else 0)
    elif hour > 23:
        return None
    return time(hour, minute)


def _make_date(year: int, month: int, day: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:
        raise ValueError("That date doesn't exist.") from None


def _upcoming(month: int, day: int, today: date) -> date:
    """This year's date, or next year's if it has already passed."""
    candidate = _make_date(today.year, month, day)
    return candidate if candidate >= today else _make_date(today.year + 1, month, day)


def _range_times(match: re.Match) -> tuple[time, time] | None:
    ap1, ap2 = match["ap1"], match["ap2"]
    if not (ap1 or ap2 or (match["m1"] and match["m2"])):
        return None  # "hw 3-4" is a title, not a time range
    inherited = ap1 is None and ap2 is not None
    start = _clock(match["h1"], match["m1"], ap1 or ap2)
    end = _clock(match["h2"], match["m2"], ap2 or ap1)
    if start is None or end is None:
        return None
    if inherited and start >= end:
        # "11-1pm" means 11am to 1pm.
        flipped = "am" if ap2[0].lower() == "p" else "pm"
        start = _clock(match["h1"], match["m1"], flipped)
    return start, end


def parse_quick_add(text: str, now: datetime) -> dict[str, Any] | None:
    """{"date", "start", "end", "title"}, or {"date", "all_day": True, "title"} when only a date is given.

    Returns None if no date or time was recognized (the caller can ask the model instead).
    Raises ValueError for impossible dates or times that don't fit in one day.
    """
    masked = text
    today = now.date()

    def take(regex: re.Pattern, accept=lambda match: True):
        """First acceptable match; it's blanked out of `masked` so later patterns can't reuse it."""
        nonlocal masked
        for match in regex.finditer(masked):
            if accept(match):
                masked = masked[:match.start()] + " " * (match.end() - match.start()) + masked[match.end():]
                return match
        return None

    duration = None
    if match := take(_DURATION_RE):
        amount = float(match["n"])
        duration = timedelta(minutes=amount * 60 if match["unit"].lower().startswith("h") else amount)

    day = None
    tonight = False
    if match := take(_ISO_RE):
        day = _make_date(int(match["y"]), int(match["mo"]), int(match["d"]))
    elif match := take(_SLASH_RE):
        if match["y"]:
            year = int(match["y"]) + (2000 if len(match["y"]) == 2 else 0)
            day = _make_date(year, int(match["mo"]), int(match["d"]))
        else:
            day = _upcoming(int(match["mo"]), int(match["d"]), today)
    elif (match := take(_MONTH_DAY_RE)) or (match := take(_DAY_MONTH_RE)):
        day = _upcoming(MONTHS[match["mon"].lower()], int(match["d"]), today)
    elif match := take(_RELATIVE_RE):
        word = match["word"].lower()
        day = today if word in ("today", "tonight") else today + timedelta(days=1)
        tonight = word == "tonight"
    elif match := take(_WEEKDAY_RE):
        delta = (WEEKDAYS[match["wd"].lower()] - today.weekday()) % 7
        if match["next"] and delta == 0:
            delta = 7
        day = today + timedelta(days=delta)

    start = end = None
    if match := take(_RANGE_RE, lambda match: _range_times(match) is not None):
        start, end = _range_times(match)
    elif match := take(_TIME_RE, lambda match: match["word"] or match["h24"] or _clock(match["h"], match["m"], match["ap"])):
        if match["word"]:
            start = time(12, 0)
        elif match["h24"]:
            start = time(int(match["h24"]), int(match["m24"]))
        else:
            start = _clock(match["h"], match["m"], match["ap"])
    elif tonight:
        start = TONIGHT_DEFAULT

    title = re.sub(r"\s+", " ", masked).strip(" ,.;:-–—")
    connector_edges = re.compile(rf"^(?:{CONNECTORS})\b\s*|\s*\b(?:{CONNECTORS})$", _FLAGS)
    while (trimmed := connector_edges.sub("", title).strip(" ,.;:-–—")) != title:
        title = trimmed
    title = (title[:1].upper() + title[1:]) if title else "Event"

    if day is None and start is None:
        return None
    if start is None:
        return {"date": day.isoformat(), "all_day": True, "title": title}
    if day is None:
        # A bare time means the next time it comes around.
        day = today if start > now.time() else today + timedelta(days=1)

    start_at = datetime.combine(day, start)
    end_at = datetime.combine(day, end) if end else start_at + (duration or timedelta(minutes=DEFAULT_MINUTES))
    if end_at <= start_at or end_at.date() != day:
        raise ValueError("The event needs to end after it starts, on the same day.")
    return {"date": day.isoformat(), "start": start_at.strftime("%H:%M"), "end": end_at.strftime("%H:%M"), "title": title}
