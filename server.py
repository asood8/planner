from flask import Flask, request, jsonify, render_template_string, send_from_directory
import requests
import json
import os
from datetime import date
from pathlib import Path

app = Flask(__name__, static_folder='output')

OLLAMA_BASE = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')

TEMPLATE_PATH = Path(__file__).parent / 'output' / 'template.html'
SYSTEM_PROMPT_PATH = Path(__file__).parent / 'prompts' / 'system_prompt.txt'
TEMPLATE_CONTENT = TEMPLATE_PATH.read_text(encoding='utf-8') if TEMPLATE_PATH.exists() else ""
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding='utf-8') if SYSTEM_PROMPT_PATH.exists() else ""

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


@app.route('/')
def index():
    if not TEMPLATE_CONTENT:
        return "Error: template.html not found", 500
    return render_template_string(
        TEMPLATE_CONTENT,
        ai_plan_html="<p>No plan generated yet. Click 'Ask AI' to generate a schedule.</p>",
        events_json="[]",
        ollama_model="phi4-mini:3.8b",
        calendar_ok=True,
        tasks_ok=True,
        gmail_ok=True
    )


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('output', filename)


@app.route('/generate', methods=['POST'])
def generate():
    payload = request.get_json() or {}
    model = payload.get('model')
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