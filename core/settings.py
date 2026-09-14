"""config.json, loaded and validated in one place.

load_settings() returns a Settings with every default filled in, so nothing else reads config.json or
keeps its own defaults. A missing config.json just means the defaults. A bad value raises ConfigError
naming the setting, e.g. "user_profile.workday_start must be an hour from 0 to 24 (got '8am')".
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.timeutil import load_zone

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_MODEL = "phi4-mini:3.8b"
FEED_SCHEMES = ("https://", "http://", "webcal://")

logger = logging.getLogger(__name__)


class ConfigError(ValueError):
    """config.json can't be used; the message says which setting and why."""


@dataclass(frozen=True)
class UserProfile:
    sleep_time: str = ""
    wake_time: str = ""
    priority_style: str = ""
    recurring_commitments: tuple[str, ...] = ()
    workday_start: int = 8
    workday_end: int = 22
    review_hour: int = 18  # when the "Wrapping up today" review appears; 24 turns it off


@dataclass(frozen=True)
class StudyBlocks:
    days_ahead: int = 3
    default_minutes: int = 60
    max_session_minutes: int = 90
    max_minutes_per_day: int = 240
    preferred_start: int = 9  # preferred study hours, from config "preferred_hours": [9, 21]
    preferred_end: int = 21
    learn_estimates: bool = True


@dataclass(frozen=True)
class ExamPrep:
    days_before: int = 7  # 0 turns exam review suggestions off
    exam_minutes: int = 240
    quiz_minutes: int = 60
    session_minutes: int = 60


@dataclass(frozen=True)
class Feed:
    name: str
    url: str = field(repr=False)  # feed URLs are private tokens; keep them out of logs and reprs


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    timezone: str = ""  # IANA name; "" means the machine's zone
    calendar_days_ahead: int = 14
    max_emails: int = 20
    include_gmail: bool = True
    user_context: str = ""
    user_profile: UserProfile = field(default_factory=UserProfile)
    study_blocks: StudyBlocks = field(default_factory=StudyBlocks)
    exam_prep: ExamPrep = field(default_factory=ExamPrep)
    ical_feeds: tuple[Feed, ...] = ()


def _whole_number(value: Any, name: str, low: int, high: int, what: str = "a whole number") -> int:
    number = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    if number is None or not low <= number <= high:
        raise ConfigError(f"{name} must be {what} from {low} to {high} (got {value!r})")
    return number


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be text (got {value!r})")
    return value.strip()


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false (got {value!r})")
    return value


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be an object like {{\"...\": ...}} (got {value!r})")
    return value


def _value(section: dict[str, Any], key: str, default: Any) -> Any:
    """A setting's raw value; missing or null means the default."""
    value = section.get(key)
    return default if value is None else value


def _user_profile(raw: dict[str, Any]) -> UserProfile:
    section = _section(raw, "user_profile")
    defaults = UserProfile()
    commitments = _value(section, "recurring_commitments", [])
    if isinstance(commitments, str):
        commitments = [commitments]
    if not isinstance(commitments, list) or not all(isinstance(item, str) for item in commitments):
        raise ConfigError(f"user_profile.recurring_commitments must be a list of text (got {commitments!r})")
    start = _whole_number(_value(section, "workday_start", defaults.workday_start), "user_profile.workday_start", 0, 24, "an hour")
    end = _whole_number(_value(section, "workday_end", defaults.workday_end), "user_profile.workday_end", 0, 24, "an hour")
    if start >= end:
        raise ConfigError(f"user_profile.workday_start ({start}) must be earlier than workday_end ({end})")
    return UserProfile(
        sleep_time=_text(_value(section, "sleep_time", ""), "user_profile.sleep_time"),
        wake_time=_text(_value(section, "wake_time", ""), "user_profile.wake_time"),
        priority_style=_text(_value(section, "priority_style", ""), "user_profile.priority_style"),
        recurring_commitments=tuple(item.strip() for item in commitments if item.strip()),
        workday_start=start,
        workday_end=end,
        review_hour=_whole_number(_value(section, "review_hour", defaults.review_hour), "user_profile.review_hour", 0, 24, "an hour"),
    )


def _study_blocks(raw: dict[str, Any]) -> StudyBlocks:
    section = _section(raw, "study_blocks")
    defaults = StudyBlocks()
    hours = _value(section, "preferred_hours", [defaults.preferred_start, defaults.preferred_end])
    if not isinstance(hours, list) or len(hours) != 2:
        raise ConfigError(f"study_blocks.preferred_hours must be two hours like [9, 21] (got {hours!r})")
    preferred_start = _whole_number(hours[0], "study_blocks.preferred_hours start", 0, 24, "an hour")
    preferred_end = _whole_number(hours[1], "study_blocks.preferred_hours end", 0, 24, "an hour")
    if preferred_start >= preferred_end:
        raise ConfigError(f"study_blocks.preferred_hours must start before it ends (got {hours!r})")
    return StudyBlocks(
        max_minutes_per_day=_whole_number(
            _value(section, "max_minutes_per_day", defaults.max_minutes_per_day), "study_blocks.max_minutes_per_day", 15, 960
        ),
        preferred_start=preferred_start,
        preferred_end=preferred_end,
        learn_estimates=_flag(_value(section, "learn_estimates", defaults.learn_estimates), "study_blocks.learn_estimates"),
        days_ahead=_whole_number(_value(section, "days_ahead", defaults.days_ahead), "study_blocks.days_ahead", 0, 30),
        default_minutes=_whole_number(
            _value(section, "default_minutes", defaults.default_minutes), "study_blocks.default_minutes", 15, 600
        ),
        max_session_minutes=_whole_number(
            _value(section, "max_session_minutes", defaults.max_session_minutes), "study_blocks.max_session_minutes", 15, 240
        ),
    )


def _exam_prep(raw: dict[str, Any]) -> ExamPrep:
    section = _section(raw, "exam_prep")
    defaults = ExamPrep()

    def number(key: str, low: int, high: int) -> int:
        return _whole_number(_value(section, key, getattr(defaults, key)), f"exam_prep.{key}", low, high)

    return ExamPrep(
        days_before=number("days_before", 0, 30),
        exam_minutes=number("exam_minutes", 15, 1200),
        quiz_minutes=number("quiz_minutes", 15, 600),
        session_minutes=number("session_minutes", 30, 240),
    )


def _feeds(raw: dict[str, Any]) -> tuple[Feed, ...]:
    entries = _value(raw, "ical_feeds", [])
    if not isinstance(entries, list):
        raise ConfigError('ical_feeds must be a list of {"name": ..., "url": ...} entries')
    feeds = []
    for index, entry in enumerate(entries, start=1):
        if isinstance(entry, str):
            entry = {"url": entry}
        if not isinstance(entry, dict):
            raise ConfigError(f"ical_feeds entry {index} must be a URL or an object with a url")
        url = str(entry.get("url") or "").strip()
        if not url:
            continue  # placeholders like the example's {"name": "Canvas", "url": ""}
        # Never echo the URL in errors: it's a private token.
        if not url.lower().startswith(FEED_SCHEMES):
            raise ConfigError(f"ical_feeds entry {index} has a url that doesn't start with https://, http://, or webcal://")
        if url.lower().startswith("webcal://"):
            url = "https://" + url[len("webcal://"):]
        feeds.append(Feed(name=str(entry.get("name") or f"Feed {index}").strip(), url=url))
    return tuple(feeds)


def settings_from_dict(raw: Any) -> Settings:
    """Validate a parsed config.json. Unknown keys (e.g. output_mode) are ignored."""
    if not isinstance(raw, dict):
        raise ConfigError("config.json must be a JSON object")
    defaults = Settings()

    zone = _text(_value(raw, "timezone", ""), "timezone")
    if zone:
        try:
            load_zone(zone)
        except ValueError as exc:
            raise ConfigError(f"timezone: {exc}") from None

    model = _text(_value(raw, "model", defaults.model), "model") or defaults.model
    return Settings(
        model=model,
        timezone=zone,
        calendar_days_ahead=_whole_number(_value(raw, "calendar_days_ahead", defaults.calendar_days_ahead), "calendar_days_ahead", 1, 60),
        max_emails=_whole_number(_value(raw, "max_emails", defaults.max_emails), "max_emails", 0, 100),
        include_gmail=_flag(_value(raw, "include_gmail", defaults.include_gmail), "include_gmail"),
        user_context=_text(_value(raw, "user_context", ""), "user_context"),
        user_profile=_user_profile(raw),
        study_blocks=_study_blocks(raw),
        exam_prep=_exam_prep(raw),
        ical_feeds=_feeds(raw),
    )


def load_settings(path: Path | None = None) -> Settings:
    """Settings from config.json (defaults if it doesn't exist). Raises ConfigError if it can't be used."""
    path = path or CONFIG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("No %s found; using the default settings.", path.name)
        return Settings()
    except OSError as exc:
        raise ConfigError(f"couldn't read {path.name}: {exc}") from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ConfigError(f"{path.name} isn't valid JSON ({exc})") from None
    return settings_from_dict(raw)
