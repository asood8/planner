from flask import Flask, Response, request, jsonify, redirect, render_template_string, send_from_directory
from markupsafe import escape
import requests
import json
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path
from time import monotonic

from ai.ollama_client import OllamaClient
from auth.google_auth import get_credentials
from core import timeutil
from core.context_builder import build_busy_times
from core.done_tasks import load_done, mark_done, record_actual, undo_done
from core.email_deadlines import scan_emails
from core.estimates import estimate_for, measure_actual
from core.logs import log_failure, setup_logging
from core.normalizer import flatten_tasks, task_key
from core.pipeline import build_plan_prompt, fetch_sources, prepare_contexts, script_safe_json, with_saved_events
from core.plan_history import get_plan, latest_plan_for, list_plans, save_plan
from core.prompt_builder import PLAN_REQUESTS
from core.quick_add import parse_quick_add
from core.saved_events import (
    add_saved_events,
    delete_saved_event,
    delete_upcoming,
    load_saved_events,
    to_calendar_events,
    update_saved_event,
)
from core.settings import ConfigError, Settings, load_settings
from core.suggestions import dismiss
from fetch.ical import fetch_feeds
from output.calendar_formatter import to_fullcalendar_events
from output.formatter import format_ai_output

# No static folder: output/ also holds Python sources, so only the dashboard file is served (below).
app = Flask(__name__, static_folder=None)
logger = logging.getLogger("planner.server")

OLLAMA_BASE = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
GOOGLE_CACHE_SECONDS = 300
GOOGLE_STATUS_KEYS = ('calendar_ok', 'tasks_ok', 'gmail_ok')
ASK_AI_FIELDS = ('date', 'start', 'end', 'title')
TIMING_FIELDS = ('date', 'start', 'end', 'all_day')
SUGGESTION_FIELDS = ('date', 'start', 'end', 'title', 'all_day', 'ref')

OUTPUT_DIR = Path(__file__).parent / 'output'
TEMPLATE_PATH = OUTPUT_DIR / 'template.html'
SYSTEM_PROMPT_PATH = Path(__file__).parent / 'prompts' / 'ask_ai_system_prompt.txt'
TEMPLATE_CONTENT = TEMPLATE_PATH.read_text(encoding='utf-8') if TEMPLATE_PATH.exists() else ""
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding='utf-8') if SYSTEM_PROMPT_PATH.exists() else ""

# Guards the Google cache; holding it during a fetch also serializes the OAuth browser flow.
_GOOGLE_LOCK = threading.Lock()
_google_cache = {}
# The current config.json problem, shown on the page until it's fixed.
_config_problem = None

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


def _load_settings():
    """config.json, read per request so edits apply without a restart.

    A file that can't be used falls back to the defaults, and the problem is shown on the page.
    """
    global _config_problem
    try:
        settings = load_settings()
        problem = None
    except ConfigError as exc:
        settings, problem = Settings(), str(exc)
        if problem != _config_problem:
            logger.error("config.json: %s (using the default settings until it's fixed)", problem)
    _config_problem = problem
    timeutil.configure(settings.timezone)
    return settings


def _configured_model(settings=None):
    return (settings or _load_settings()).model


def _requested_model(payload, settings):
    """The model picked in the page's dropdown, else the configured one."""
    model = payload.get('model')
    return model.strip() if isinstance(model, str) and model.strip() else _configured_model(settings)


def _google_data(settings, refresh=False):
    """Google data plus iCal feeds: (events, tasks, emails, status, error), cached for GOOGLE_CACHE_SECONDS."""
    with _GOOGLE_LOCK:
        cached = _google_cache.get('data')
        if cached and not refresh and monotonic() - _google_cache['fetched_at'] < GOOGLE_CACHE_SECONDS:
            return cached

        try:
            creds = get_credentials()
        except Exception as exc:
            log_failure(logger, "Google sign-in failed", exc)
            # Feeds don't need Google, so they still load.
            feed_events, feed_deadlines, feeds_ok = fetch_feeds(settings)
            gmail_status = False if settings.include_gmail else None
            status = {'calendar_ok': False, 'tasks_ok': False, 'gmail_ok': gmail_status, 'feeds_ok': feeds_ok}
            return feed_events, feed_deadlines, [], status, str(exc)

        events, tasks, emails, status = fetch_sources(creds, settings)
        data = (events, tasks, emails, status, None)
        # Only cache when Google succeeded so a failed source is retried on the next load;
        # a broken feed alone is retried when the cache expires.
        if all(status.get(key) is not False for key in GOOGLE_STATUS_KEYS):
            _google_cache.update(data=data, fetched_at=monotonic())
        return data


def _dashboard(settings):
    """Google data plus saved events, normalized, with suggestions."""
    events, tasks, emails, status, error = _google_data(settings)
    events, day_context, week_context, suggestions = prepare_contexts(events, tasks, emails, settings)
    return {
        'events': events,
        'day': day_context,
        'week': week_context,
        'suggestions': suggestions,
        'emails': emails,
        'status': status,
        'error': error,
    }


def _notices(state):
    config_notice = [f"config.json problem: {_config_problem}. Using the default settings until it's fixed."] if _config_problem else []
    return config_notice + state['suggestions']['notices']


def _todays_plan_text():
    plan = latest_plan_for(timeutil.today())
    return plan['text'] if plan else None


def _calendar_events(state, plan_text):
    return to_fullcalendar_events(state['day'], state['week'], plan_text, state['events'], state['suggestions']['items'])


def _events_from_model(note_text, model, settings):
    """Ask Ollama to turn notes into events that avoid existing commitments.

    Returns (events, None) with only the schema's fields, or (None, error_response).
    """
    today = timeutil.today()
    busy_times = build_busy_times(with_saved_events(_google_data(settings)[0]), today)
    sections = [
        SYSTEM_PROMPT,
        f"Today's date is {today.isoformat()} ({today.strftime('%A')}).",
        f"EXISTING CALENDAR (don't schedule over these):\n{busy_times}",
        note_text,
    ]
    full_prompt = "\n\n".join(section for section in sections if section)

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
        return None, (jsonify({'error': f'Ollama server not reachable on {OLLAMA_BASE}'}), 502)
    except requests.exceptions.HTTPError as exc:
        return None, (jsonify({'error': exc.response.text if exc.response is not None else str(exc)}), 502)

    raw_content = r.json().get('response', '')
    try:
        parsed = json.loads(raw_content)
        raw_events = parsed.get('events', []) if isinstance(parsed, dict) else []
    except ValueError:
        raw_events = []
    if not isinstance(raw_events, list):
        raw_events = []

    # Only the schema's fields: the model shouldn't be able to mark events as accepted suggestions.
    return [{key: event.get(key) for key in ASK_AI_FIELDS} for event in raw_events if isinstance(event, dict)], None


@app.route('/')
def index():
    if not TEMPLATE_CONTENT:
        return "Error: template.html not found", 500
    settings = _load_settings()
    if request.args.get('refresh') == '1':
        _google_data(settings, refresh=True)
        return redirect('/')

    state = _dashboard(settings)
    plan_text = _todays_plan_text()
    if state['error']:
        sidebar_html = f"<p>Couldn't connect to Google: {escape(state['error'])}</p>"
    elif plan_text:
        sidebar_html = format_ai_output(plan_text)
    else:
        sidebar_html = "<p>No plan for today yet. Generate one, or add your notes to the calendar below.</p>"

    return render_template_string(
        TEMPLATE_CONTENT,
        ai_plan_html=sidebar_html,
        events_json=script_safe_json(_calendar_events(state, plan_text)),
        notices=_notices(state),
        done_tasks=load_done(),
        estimate_notes=state['suggestions'].get('estimates', []),
        ollama_model=_configured_model(settings),
        live=True,
        **state['status']
    )


@app.route('/api/events')
def calendar_events():
    """The calendar's events, notices, and done list, so the page can refresh without reloading."""
    state = _dashboard(_load_settings())
    return jsonify({
        'events': _calendar_events(state, _todays_plan_text()),
        'notices': _notices(state),
        'done': load_done(),
        'estimates': state['suggestions'].get('estimates', []),
    })


@app.route('/planner_dashboard.html')
def last_dashboard():
    """The static dashboard written by the last plan.py run."""
    return send_from_directory(OUTPUT_DIR, 'planner_dashboard.html')


@app.route('/ollama/status')
def ollama_status():
    """Whether Ollama answers, and which models are pulled (for the status dot and model picker)."""
    default = _configured_model()
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
        r.raise_for_status()
        models = sorted({m.get('name') for m in r.json().get('models', []) if isinstance(m, dict) and m.get('name')})
    except (requests.exceptions.RequestException, ValueError, AttributeError):
        return jsonify({'running': False, 'models': [], 'default': default})
    return jsonify({'running': True, 'models': models, 'default': default})


@app.route('/generate', methods=['POST'])
def generate():
    """Ask AI: turn notes into calendar events, avoiding existing commitments, and save them."""
    payload = request.get_json(silent=True) or {}
    settings = _load_settings()
    user_prompt = payload.get('prompt')
    if not user_prompt:
        return jsonify({'error': 'missing prompt'}), 400

    events, error = _events_from_model(user_prompt, _requested_model(payload, settings), settings)
    if error is not None:
        return error
    saved = add_saved_events(events)
    return jsonify({'events': saved, 'skipped': len(events) - len(saved)})


@app.route('/quick-add', methods=['POST'])
def quick_add():
    """One event from text like "gym tomorrow 5pm"; falls back to the model when no date or time is recognized."""
    payload = request.get_json(silent=True) or {}
    text = str(payload.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Type something to add, like "gym tomorrow 5pm".'}), 400
    settings = _load_settings()
    try:
        parsed = parse_quick_add(text, timeutil.now())
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if parsed is not None:
        return jsonify({'events': add_saved_events([parsed]), 'parsed': True})

    events, error = _events_from_model(f"Temporary note:\n{text}", _requested_model(payload, settings), settings)
    if error is not None:
        return error
    return jsonify({'events': add_saved_events(events), 'parsed': False})


@app.route('/events/<event_id>', methods=['DELETE'])
def delete_event(event_id):
    """Delete a saved event; ?batch=1 also deletes the others created by the same request."""
    removed = delete_saved_event(event_id, include_batch=request.args.get('batch') == '1')
    if not removed:
        return jsonify({'error': 'event not found'}), 404
    return jsonify({'removed': removed})


@app.route('/events/<event_id>', methods=['PATCH'])
def move_event(event_id):
    """Move or resize a saved event (drag and drop on the calendar)."""
    changes = request.get_json(silent=True) or {}
    _load_settings()  # applies the configured time zone
    try:
        updated = update_saved_event(event_id, {key: changes[key] for key in TIMING_FIELDS if key in changes})
    except KeyError:
        return jsonify({'error': 'event not found'}), 404
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'event': updated})


@app.route('/suggestions/accept', methods=['POST'])
def accept_suggestion():
    """Save a suggestion as a local event; its ref keeps it from being suggested again."""
    item = (request.get_json(silent=True) or {}).get('suggestion')
    if not isinstance(item, dict) or not item.get('ref'):
        return jsonify({'error': 'missing suggestion'}), 400
    saved = add_saved_events([{key: item.get(key) for key in SUGGESTION_FIELDS}])
    if not saved:
        return jsonify({'error': 'it is invalid or already on the calendar'}), 409
    return jsonify({'saved': saved})


@app.route('/suggestions/dismiss', methods=['POST'])
def dismiss_suggestion():
    ref = (request.get_json(silent=True) or {}).get('ref')
    if not isinstance(ref, str) or not ref.strip():
        return jsonify({'error': 'missing ref'}), 400
    dismiss(ref)
    return jsonify({'dismissed': ref})


@app.route('/suggestions/scan-emails', methods=['POST'])
def scan_email_deadlines():
    """Run the model over unread emails it hasn't seen. {"scanned": n}, or {"busy": true} if a scan is running."""
    payload = request.get_json(silent=True) or {}
    settings = _load_settings()
    if not settings.include_gmail:
        return jsonify({'scanned': 0})
    emails = _google_data(settings)[2]
    try:
        scanned = scan_emails(emails, OllamaClient(base_url=OLLAMA_BASE), _requested_model(payload, settings), timeutil.today())
    except RuntimeError as exc:
        logger.warning("Email deadline scan skipped: %s", exc)
        return jsonify({'scanned': 0, 'error': str(exc)})
    if scanned is None:
        return jsonify({'scanned': 0, 'busy': True})
    return jsonify({'scanned': scanned})


@app.route('/tasks/done', methods=['POST'])
def task_done():
    """Hide a task in the planner (Google Tasks itself is read-only and unchanged) and measure how long it took.

    The measurement (study sessions for the task that had started) is stored with the estimate the planner
    used, for core/estimates.py to learn from; the page then asks the user to confirm or correct it.
    Sessions for the task that haven't started yet are removed.
    """
    payload = request.get_json(silent=True) or {}
    key = payload.get('key')
    if not isinstance(key, str) or not key.strip():
        return jsonify({'error': 'missing task key'}), 400
    settings = _load_settings()
    now = timeutil.now()
    task = next((task for task in flatten_tasks(_google_data(settings)[1]) if task_key(task) == key), None)
    actual = measure_actual(key, to_calendar_events(load_saved_events()), now)
    measurement = {'actual': actual or None}
    estimate_minutes = None
    if task is not None:
        # The learner compares actual time with the estimate before any learning was applied.
        estimate = estimate_for(task, settings.study_blocks, None)
        estimate_minutes = estimate.base
        measurement.update(list=str(task.get('list') or ''), estimate=estimate.base, from_task=estimate.from_task)
    mark_done(key, str(payload.get('title') or ''), measurement)
    removed = delete_upcoming(f"study:{key}", now)
    return jsonify({'done': key, 'actual_minutes': actual, 'estimate_minutes': estimate_minutes, 'removed_sessions': removed})


@app.route('/tasks/time', methods=['POST'])
def task_time():
    """Record how long a finished task really took, as the user reported it."""
    payload = request.get_json(silent=True) or {}
    key = payload.get('key')
    minutes = payload.get('minutes')
    if not isinstance(key, str) or not key.strip():
        return jsonify({'error': 'missing task key'}), 400
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 1 <= minutes <= 1440:
        return jsonify({'error': 'minutes must be a number from 1 to 1440'}), 400
    if not record_actual(key, int(minutes)):
        return jsonify({'error': 'task not found in the done list'}), 404
    return jsonify({'key': key, 'actual': int(minutes)})


@app.route('/tasks/undo', methods=['POST'])
def task_undo():
    key = (request.get_json(silent=True) or {}).get('key')
    if not isinstance(key, str) or not undo_done(key):
        return jsonify({'error': 'task not found in the done list'}), 404
    return jsonify({'undone': key})


@app.route('/plans')
def plans():
    return jsonify({'plans': list_plans()})


@app.route('/plans/<plan_id>')
def plan_detail(plan_id):
    entry = get_plan(plan_id)
    if entry is None:
        return jsonify({'error': 'plan not found'}), 404
    summary = {key: entry.get(key) for key in ('id', 'date', 'created', 'mode', 'model')}
    return jsonify({**summary, 'html': format_ai_output(entry['text'])})


@app.route('/plan', methods=['POST'])
def plan():
    """Generate the full plan, streamed as NDJSON: {"token"} lines, then {"done", "id", "html", "events"} or {"error"}."""
    payload = request.get_json(silent=True) or {}
    mode = payload.get('mode') if payload.get('mode') in PLAN_REQUESTS else 'daily'
    note = str(payload.get('note') or '')
    settings = _load_settings()
    model = _requested_model(payload, settings)
    state = _dashboard(settings)
    prompt, _ = build_plan_prompt(state['day'], state['week'], settings, mode, note, state['suggestions'])
    client = OllamaClient(base_url=OLLAMA_BASE)

    def stream():
        chunks = []
        try:
            for token in client.iter_generate(prompt, model=model):
                chunks.append(token)
                yield json.dumps({'token': token}) + '\n'
        except Exception as exc:
            log_failure(logger, "Plan generation failed", exc)
            yield json.dumps({'error': str(exc)}) + '\n'
            return

        text = ''.join(chunks)
        if not text.strip():
            logger.warning("The model returned an empty plan.")
            yield json.dumps({'error': 'The model returned an empty plan.'}) + '\n'
            return
        entry = save_plan(text, mode, model)
        logger.info("Plan saved (%s, %s).", mode, model)
        plan_events = [event for event in _calendar_events(state, text) if event.get('category') == 'plan']
        yield json.dumps({'done': True, 'id': entry['id'], 'html': format_ai_output(text), 'events': plan_events}) + '\n'

    return Response(stream(), mimetype='application/x-ndjson')


if __name__ == '__main__':
    setup_logging(console=True)
    port = int(os.getenv('PORT', '5000'))
    url = f"http://127.0.0.1:{port}/"
    logger.info("Serving planner on %s", url)
    if '--open' in sys.argv[1:]:
        # Give the server a moment to start listening before the browser asks for the page.
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    app.run(host='127.0.0.1', port=port)
