# Local AI Planner

Reads Google Calendar, Google Tasks, and unread Gmail, and generates a daily/weekly
plan using a locally-run Ollama model. No cloud AI calls, no data leaves your machine.

## Requirements
- Python 3.11+
- [Ollama](https://ollama.com) installed and running, with a model pulled (e.g. `ollama pull phi4-mini`)
- A Google Cloud project with the Calendar, Tasks, and Gmail APIs enabled

## Setup
1. `python -m venv .venv`
2. `.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (Mac/Linux)
3. `pip install -r requirements.txt`
4. Create OAuth credentials in Google Cloud Console (Desktop app type), download as `credentials.json` in the project root. Add yourself as a test user under OAuth consent screen while the app is unverified.
5. Copy `config.example.json` to `config.json` and fill in your own context.

## Running it

**Full plan from your Google data.** Fetches Calendar, Tasks, and Gmail, asks Ollama for a plan, and writes `output/planner_dashboard.html`:

    python plan.py --daily      # or --weekly, or --all (the default with no flag)

On Windows, `run_planner.bat` / `run_planner.ps1` do the same using `.venv`.

**Live calendar + notes to events.** A local web app that shows your Google Calendar events and Tasks, fetched fresh on each page load. The "Ask AI" button turns your notes into calendar events:

    python server.py

Then open http://127.0.0.1:5000

The first run of either one opens a browser window for Google's OAuth consent (with `server.py`, the page keeps loading until you finish signing in). This only happens once; after that, `token.json` is cached locally.

## Tests

    python -m unittest discover -s tests -v