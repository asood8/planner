from __future__ import annotations

from html import escape
from typing import Any

import markdown


def format_ai_output(ai_text: str) -> str:
    """Convert AI-generated markdown text into safe HTML for the sidebar view."""
    if not ai_text:
        return "<p>No plan available.</p>"

    html = markdown.markdown(ai_text, extensions=["extra", "fenced_code", "tables"])
    return f"<div class=\"plan-html\">{html}</div>"
