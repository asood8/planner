from __future__ import annotations

from pathlib import Path
from typing import Any

from core.settings import Settings

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "planner_system_prompt.txt"

PLAN_REQUESTS = {
    "daily": "Generate a daily plan only.",
    "weekly": "Generate a weekly overview only.",
    "all": "Generate a daily plan, a weekly overview, and long-term items to not forget.",
}


def _load_system_prompt() -> str:
    with SYSTEM_PROMPT_PATH.open("r", encoding="utf-8") as handle:
        return handle.read().strip()


def _user_context(settings: Settings) -> str:
    """The user's own context text plus whichever profile details are filled in."""
    profile = settings.user_profile
    lines = [
        f"{label}: {value}"
        for label, value in (
            ("Sleep time", profile.sleep_time),
            ("Wake time", profile.wake_time),
            ("Priority style", profile.priority_style),
        )
        if value
    ]
    if profile.recurring_commitments:
        lines.append("Recurring commitments: " + "; ".join(profile.recurring_commitments))
    parts = [settings.user_context]
    if lines:
        parts.append("User profile:\n- " + "\n- ".join(lines))
    return "\n\n".join(part for part in parts if part)


def build_prompt(
    day_context: dict[str, Any],
    week_context: dict[str, Any],
    request: str,
    context_text: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Assemble the system prompt, user context, dynamic context, and request into one prompt."""
    settings = settings or Settings()
    dynamic_context = f"Current date: {day_context.get('date', 'unknown')}\n\n{context_text.strip() if context_text else ''}"

    return "\n\n".join(
        [
            _load_system_prompt(),
            "USER CONTEXT",
            _user_context(settings),
            "DYNAMIC CONTEXT",
            dynamic_context,
            f"REQUEST: {request}",
        ]
    )
