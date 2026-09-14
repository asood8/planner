import argparse
import logging
import sys
from pathlib import Path

from ai.ollama_client import OllamaClient
from auth.google_auth import get_credentials
from core import timeutil
from core.email_deadlines import scan_emails
from core.logs import log_failure, setup_logging
from core.pipeline import build_plan_prompt, fetch_sources, prepare_contexts, script_safe_json
from core.plan_history import save_plan
from core.settings import ConfigError, Settings, load_settings
from output.calendar_formatter import to_fullcalendar_events
from output.formatter import format_ai_output
from output.notify import morning_summary, send_toast, server_is_running
from jinja2 import Environment, FileSystemLoader

BASE_DIR = Path(__file__).resolve().parent
SERVER_URL = "http://127.0.0.1:5000/"

logger = logging.getLogger("planner.cli")


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
    settings: Settings,
    output_path: str | None = None,
    calendar_events: list[dict] | None = None,
    suggestions: dict | None = None,
    feeds_ok: bool | None = None,
) -> str:
    """Render the dashboard. A status of None means the source was not fetched (shown grey, or hidden for feeds).

    `suggestions` is build_suggestions() output: {"items": [...], "notices": [...]}.
    """
    suggestions = suggestions or {}
    template_dir = BASE_DIR / "output"
    environment = Environment(loader=FileSystemLoader(template_dir))
    template = environment.get_template("template.html")
    events_json = script_safe_json(
        to_fullcalendar_events(day_context, week_context, result, calendar_events, suggestions.get("items"))
    )
    html = template.render(
        events_json=events_json,
        ai_plan_html=format_ai_output(result),
        notices=suggestions.get("notices", []),
        calendar_ok=calendar_ok,
        tasks_ok=tasks_ok,
        gmail_ok=gmail_ok,
        feeds_ok=feeds_ok,
        ollama_model=settings.model,
    )

    output_file = Path(output_path) if output_path else template_dir / "planner_dashboard.html"
    output_file.write_text(html, encoding="utf-8")
    return str(output_file)


def notify_plan(result, plan_ok, day_context, week_context, events, suggestions, dashboard_path) -> None:
    """Windows toast with what's due and the next few items; clicking opens the web app (or the file)."""
    entries = to_fullcalendar_events(day_context, week_context, result if plan_ok else None, events, suggestions["items"])
    title, lines = morning_summary(entries, day_context, suggestions["notices"], timeutil.now(), plan_ok)
    open_url = SERVER_URL if server_is_running() else Path(dashboard_path).resolve().as_uri()
    if send_toast(title, lines, open_url):
        logger.info("Showed the plan notification.")
    else:
        logger.warning("Couldn't show a Windows notification.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a daily/weekly planner from your Google data")
    parser.add_argument("--daily", action="store_true", help="Generate a daily plan only")
    parser.add_argument("--weekly", action="store_true", help="Generate a weekly overview only")
    parser.add_argument("--all", action="store_true", help="Generate daily, weekly, and long-term guidance")
    parser.add_argument(
        "--notify", action="store_true", help="Show a Windows notification when done (for the scheduled morning run)"
    )
    return parser


def run(mode: str, settings: Settings, notify: bool) -> None:
    creds = get_credentials()
    client = OllamaClient(base_url="http://localhost:11434")

    events, tasks, emails, status = fetch_sources(creds, settings)
    if emails:
        try:
            scan_emails(emails, client, settings.model, timeutil.today())
        except RuntimeError as exc:
            logger.warning("Email deadline scan skipped: %s", exc)
    events, day_context, week_context, suggestions = prepare_contexts(events, tasks, emails, settings)
    prompt, context_text = build_plan_prompt(day_context, week_context, settings, mode, suggestions=suggestions)

    plan_ok = False
    try:
        result = client.generate(prompt, model=settings.model, stream=False)
        plan_ok = bool(result.strip())
        if plan_ok:
            save_plan(result, mode, settings.model)
            logger.info("Plan saved (%s, %s).", mode, settings.model)
        else:
            logger.warning("The model returned an empty plan.")
        print(format_output(result, mode))
    except Exception as exc:
        log_failure(logger, "Plan generation failed", exc)
        result = (
            f"Planner run completed with fallback context.\n\n"
            f"Ollama generation failed: {exc}\n\n"
            f"Prompt assembled successfully."
        )
        # Console only: the prompt holds calendar and email content, which never goes in the log file.
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
        settings,
        calendar_events=events,
        suggestions=suggestions,
        feeds_ok=status.get("feeds_ok"),
    )
    logger.info("Dashboard written to %s", dashboard_path)

    if notify:
        notify_plan(result, plan_ok, day_context, week_context, events, suggestions, dashboard_path)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.weekly and args.daily:
        parser.error("Use either --daily or --weekly, or --all")

    mode = "all" if args.all else "weekly" if args.weekly else "daily" if args.daily else "all"

    setup_logging(console=True)
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("config.json: %s", exc)
        return 2
    timeutil.configure(settings.timezone)

    logger.info("Planner run started (%s).", mode)
    try:
        run(mode, settings, args.notify)
    except Exception:
        # The traceback lands in data/planner.log, which is all an unattended morning run leaves behind.
        logger.exception("Planner run failed")
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
