# Local AI Planner

Reads Google Calendar, Google Tasks, and unread Gmail, and generates a daily/weekly
plan using a locally-run Ollama model. No cloud AI calls, no data leaves your machine.

## Requirements
- Python 3.11+
- [Ollama](https://ollama.com) installed and running, with a model pulled (e.g. `ollama pull phi4-mini`)
- A Google Cloud project with the Calendar, Tasks, and Gmail APIs enabled

## Setup
1. `python -m venv venv`
2. `.\venv\Scripts\Activate.ps1` (Windows) or `source venv/bin/activate` (Mac/Linux)
3. `pip install -r requirements.txt`
4. Create OAuth credentials in Google Cloud Console (Desktop app type), download as `credentials.json` in the project root. Add yourself as a test user under OAuth consent screen while the app is unverified.
5. Copy `config.example.json` to `config.json` and fill in your own context.

## Running it

python server.py

Then open http://127.0.0.1:5000

First run of either will open a browser window for Google's OAuth consent — this only happens once, after which `token.json` is cached locally.