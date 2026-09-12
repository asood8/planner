import argparse
import sys
from pathlib import Path

from ai.ollama_client import OllamaClient
from auth.google_auth import get_credentials
from core.context_builder import build_context
from core.pipeline import fetch_sources, load_config, normalize_sources, script_safe_json
from core.prompt_builder import build_prompt
from output.calendar_formatter import to_fullcalendar_events
from output.formatter import format_ai_output
from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).resolve().parent


def format_output(result: str, mode: str) -> str:
    heading = {
        "daily": "DAILY PLAN",
        "weekly": "WEEKLY OVERVIEW",
        "all": "DAILY PLAN + WEEKLY OVERVIEW",
    }.get(mode, "PLANNER OUTPUT")
    return f"{heading}\n{'=' * len(heading)}\n\n{result.strip()}"


def render_dashboard(
    result: str,
    day_context: dict,
    week_context: dict,
    calendar_ok: bool,
    tasks_ok: bool,
    gmail_ok: bool | None,
    config: dict,
    output_path: str | None = None,
    calendar_events: list[dict] | None = None,
) -> str:
    """Render the dashboard. A status of None means the source was not fetched (shown grey)."""
    template_dir = BASE_DIR / "output"
    environment = Environment(loader=FileSystemLoader(template_dir))
    template = environment.get_template("template.html")
    events_json = script_safe_json(to_fullcalendar_events(day_context, week_context, result, calendar_events))
    ai_plan_html = format_ai_output(result)
    ollama_model = config.get("model", "phi4-mini:3.8b")
    html = template.render(
        events_json=events_json,
        ai_plan_html=ai_plan_html,
        calendar_ok=calendar_ok,
        tasks_ok=tasks_ok,
        gmail_ok=gmail_ok,
        ollama_model=ollama_model,
    )

    output_file = Path(output_path) if output_path else template_dir / "planner_dashboard.html"
    output_file.write_text(html, encoding="utf-8")
    return str(output_file)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a daily/weekly planner from your Google data")
    parser.add_argument("--daily", action="store_true", help="Generate a daily plan only")
    parser.add_argument("--weekly", action="store_true", help="Generate a weekly overview only")
    parser.add_argument("--all", action="store_true", help="Generate daily, weekly, and long-term guidance")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.weekly and args.daily:
        parser.error("Use either --daily or --weekly, or --all")

    mode = "all" if args.all else "weekly" if args.weekly else "daily" if args.daily else "all"

    config = load_config()
    creds = get_credentials()

    events, tasks, emails, status = fetch_sources(creds, config)
    day_context, week_context = normalize_sources(events, tasks, emails, config)
    context_text = build_context(day_context, week_context, max_emails=config.get("max_emails", 20))

    if mode == "daily":
        request = "Generate a daily plan only."
    elif mode == "weekly":
        request = "Generate a weekly overview only."
    else:
        request = "Generate a daily plan, a weekly overview, and long-term items to not forget."

    prompt = build_prompt(day_context, week_context, request, context_text)

    client = OllamaClient(base_url="http://localhost:11434")
    try:
        result = client.generate(prompt, model=config.get("model", "phi4-mini:3.8b"), stream=False)
        print(format_output(result, mode))
    except Exception as exc:
        result = (
            f"Planner run completed with fallback context.\n\n"
            f"Ollama generation failed: {exc}\n\n"
            f"Prompt assembled successfully."
        )
        print(f"Ollama generation failed: {exc}")
        print("\nPROMPT:\n")
        print(prompt)
        print("\nCONTEXT:\n")
        print(context_text)

    dashboard_path = render_dashboard(
        result,
        day_context,
        week_context,
        status["calendar_ok"],
        status["tasks_ok"],
        status["gmail_ok"],
        config,
        calendar_events=events,
    )
    print(f"\nDashboard written to: {dashboard_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
