"""What "local time" means for the whole app, in one place.

Local time is the IANA zone from config.json's "timezone" (e.g. "America/New_York") once configure()
has been called with it; until then, or when it's blank, it's the machine's own zone. Naive datetimes
always mean local wall-clock time, never UTC. A wall-clock time on a given day gets *that day's* UTC
offset, so daylight-saving changes don't shift anything by an hour.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_zone: ZoneInfo | None = None


def load_zone(name: str) -> ZoneInfo:
    """ZoneInfo for an IANA name, or ValueError with a readable message."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {name!r}; use a name like 'America/New_York'") from exc


def configure(name: str | None) -> None:
    """Use this IANA zone as local time. None or "" means the machine's zone."""
    global _zone
    _zone = load_zone(name) if name else None


def now() -> datetime:
    """The current time as an aware local datetime."""
    return datetime.now(_zone) if _zone else datetime.now().astimezone()


def today() -> date:
    return now().date()


def to_local(value: datetime) -> datetime:
    """An aware local datetime. Naive values are taken as local wall-clock time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=_zone) if _zone else value.astimezone()
    return value.astimezone(_zone) if _zone else value.astimezone()


def at(day: date, clock: time) -> datetime:
    """Local wall-clock `clock` on `day`, with that day's UTC offset."""
    return to_local(datetime.combine(day, clock))


def parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_utc(value: Any) -> datetime | None:
    """Aware UTC datetime for ordering and overlap checks.

    Accepts datetimes (naive = local), plain dates (local midnight), and ISO strings.
    """
    if isinstance(value, str):
        value = parse_iso(value)
    if isinstance(value, datetime):
        return to_local(value).astimezone(timezone.utc)
    if isinstance(value, date):
        return at(value, time.min).astimezone(timezone.utc)
    return None


def local_day(value: Any) -> date | None:
    """The local calendar day of an event time; plain dates come back as they are."""
    if isinstance(value, str):
        value = parse_iso(value)
    if isinstance(value, datetime):
        return to_local(value).date()
    if isinstance(value, date):
        return value
    return None


def wall_clock(value: Any) -> str | None:
    """Local "YYYY-MM-DDTHH:MM:SS" without an offset, the form FullCalendar gets."""
    moment = to_utc(value)
    return to_local(moment).strftime("%Y-%m-%dT%H:%M:%S") if moment else None


def twelve_hour(clock_text: str) -> str:
    """ "23:59" -> "11:59 PM". Anything that isn't HH:MM comes back unchanged."""
    try:
        return datetime.strptime(clock_text, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return clock_text
