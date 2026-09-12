from __future__ import annotations

import re

import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

SAFE_URL_SCHEMES = {"http", "https", "mailto"}
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")


def _is_safe_url(value: str) -> bool:
    # Browsers ignore whitespace/control characters inside a scheme ("java\tscript:").
    compact = "".join(ch for ch in value if ch > " ")
    match = _SCHEME_RE.match(compact)
    return match is None or match.group(1).lower() in SAFE_URL_SCHEMES


class _StripUnsafeAttributes(Treeprocessor):
    """Drop event-handler attributes (attr_list allows them) and non-http(s)/mailto URLs."""

    def run(self, root):
        for element in root.iter():
            for name in list(element.attrib):
                value = element.attrib[name]
                if name.lower().startswith("on") or (name in ("href", "src") and not _is_safe_url(value)):
                    del element.attrib[name]


class _SafeMarkdown(Extension):
    """Render model output as markdown only: raw HTML is escaped, not passed through."""

    def extendMarkdown(self, md):
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        md.treeprocessors.register(_StripUnsafeAttributes(md), "strip_unsafe_attributes", 5)


def format_ai_output(ai_text: str) -> str:
    """Convert AI-generated markdown text into safe HTML for the sidebar view."""
    if not ai_text:
        return "<p>No plan available.</p>"

    # The plan is influenced by email snippets and event titles, so treat it as untrusted.
    html = markdown.markdown(ai_text, extensions=["extra", "fenced_code", "tables", _SafeMarkdown()])
    return f"<div class=\"plan-html\">{html}</div>"
