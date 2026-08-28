from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = BASE_DIR / "prompts" / "planner_system_prompt.txt"
CONFIG_PATH = BASE_DIR / "config.json"


def _load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_system_prompt() -> str:
    with SYSTEM_PROMPT_PATH.open("r", encoding="utf-8") as handle:
        return handle.read().strip()


def build_prompt(day_context: dict[str, Any], week_context: dict[str, Any], request: str, context_text: str | None = None) -> str:
    """Assemble the system prompt, user context, dynamic context, and request into one prompt."""
    config = _load_config()
    system_prompt = _load_system_prompt()

    user_context = config.get("user_context", "")
    user_profile = config.get("user_profile", {})
    if user_profile:
        profile_lines = [
            f"Sleep time: {user_profile.get('sleep_time', 'unknown')}",
            f"Wake time: {user_profile.get('wake_time', 'unknown')}",
            f"Priority style: {user_profile.get('priority_style', 'unknown')}",
        ]
        if user_profile.get("recurring_commitments"):
            profile_lines.append(
                "Recurring commitments: " + "; ".join(user_profile["recurring_commitments"])
            )
        user_context = f"{user_context}\n\nUser profile:\n- " + "\n- ".join(profile_lines)

    dynamic_context = f"Current date: {day_context.get('date', 'unknown')}\n\n{context_text.strip() if context_text else ''}"

    return "\n\n".join(
        [
            system_prompt,
            "USER CONTEXT",
            user_context.strip(),
            "DYNAMIC CONTEXT",
            dynamic_context,
            f"REQUEST: {request}",
        ]
    )