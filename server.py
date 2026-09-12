from flask import Flask, request, jsonify, render_template_string, send_from_directory
from markupsafe import escape
import requests
import json
import os
import threading
from datetime import date
from pathlib import Path

from auth.google_auth import get_credentials
from core.pipeline import fetch_sources, normalize_sources, script_safe_json
from output.calendar_formatter import to_fullcalendar_events

# No static folder: output/ also holds Python sources, so only the dashboard file is served (below).
app = Flask(__name__, static_folder=None)

OLLAMA_BASE = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
DEFAULT_MODEL = 'phi4-mini:3.8b'

OUTPUT_DIR = Path(__file__).parent / 'output'
TEMPLATE_PATH = OUTPUT_DIR / 'template.html'
SYSTEM_PROMPT_PATH = Path(__file__).parent / 'prompts' / 'ask_ai_system_prompt.txt'
CONFIG_PATH = Path(__file__).parent / 'config.json'
TEMPLATE_CONTENT = TEMPLATE_PATH.read_text(encoding='utf-8') if TEMPLATE_PATH.exists() else ""
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding='utf-8') if SYSTEM_PROMPT_PATH.exists() else ""

# Serializes Google sign-in so concurrent page loads don't each start an OAuth browser flow.
_CREDENTIALS_LOCK = threading.Lock()

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "title": {"type": "string"}
                },
                "required": ["date", "start", "end", "title"]
            }
        }
    },
    "required": ["events"]
}


def _load_config():
    """config.json, read per request so edits apply without a restart. Missing/invalid -> {}."""
    try:
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _configured_model(config=None):
    config = _load_config() if config is None else config
    return config.get('model') or DEFAULT_MODEL


def _load_dashboard_data(config):
    """Fetch and normalize Google data. Returns (events_json, status, error_html or None)."""
    try:
        with _CREDENTIALS_LOCK:
            creds = get_credentials()
    except Exception as exc:
        print(f"Warning: Google sign-in failed: {exc}")
        gmail_status = False if config.get('include_gmail', True) else None
        status = {'calendar_ok': False, 'tasks_ok': False, 'gmail_ok': gmail_status}
        return "[]", status, f"<p>Couldn't connect to Google: {escape(str(exc))}</p>"

    events, tasks, emails, status = fetch_sources(creds, config)
    day_context, week_context = normalize_sources(events, tasks, emails, config)
    events_json = script_safe_json(to_fullcalendar_events(day_context, week_context, None, events))
    return events_json, status, None


@app.route('/')
def index():
    if not TEMPLATE_CONTENT:
        return "Error: template.html not found", 500
    config = _load_config()
    events_json, status, error_html = _load_dashboard_data(config)
    return render_template_string(
        TEMPLATE_CONTENT,
        ai_plan_html=error_html or "<p>No plan generated yet. Click 'Ask AI' to generate a schedule.</p>",
        events_json=events_json,
        ollama_model=_configured_model(config),
        **status
    )


@app.route('/planner_dashboard.html')
def last_dashboard():
    """The static dashboard written by the last plan.py run."""
    return send_from_directory(OUTPUT_DIR, 'planner_dashboard.html')


@app.route('/generate', methods=['POST'])
def generate():
    payload = request.get_json() or {}
    model = payload.get('model') or _configured_model()
    user_prompt = payload.get('prompt')
    if not user_prompt:
        return jsonify({'error': 'missing prompt'}), 400

    today = date.today()
    today_line = f"Today's date is {today.isoformat()} ({today.strftime('%A')})."
    full_prompt = f"{SYSTEM_PROMPT}\n\n{today_line}\n\n{user_prompt}" if SYSTEM_PROMPT else f"{today_line}\n\n{user_prompt}"

    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                'model': model,
                'prompt': full_prompt,
                'format': EVENT_SCHEMA,
                'stream': False,
                'options': {'temperature': 0}
            },
            timeout=300
        )
        r.raise_for_status()
    except requests.exceptions.ConnectionError:
        return jsonify({'error': f'Ollama server not reachable on {OLLAMA_BASE}'}), 502
    except requests.exceptions.HTTPError as exc:
        return jsonify({'error': exc.response.text if exc.response is not None else str(exc)}), 502

    raw_content = r.json().get('response', '')

    try:
        parsed = json.loads(raw_content)
        events = parsed.get('events', []) if isinstance(parsed, dict) else []
    except ValueError:
        events = []

    return jsonify({'events': events})


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    print(f"Serving planner on http://127.0.0.1:{port}/")
    app.run(host='127.0.0.1', port=port)
