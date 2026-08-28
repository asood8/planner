Planner — Local AI-assisted scheduling
=====================================

Overview
--------
A small local planner that fetches your Google Calendar, Tasks, and unread Gmail messages, builds context, sends a prompt to a local Ollama model, and renders a browsable dashboard (FullCalendar) containing the AI-generated plan and parsed calendar blocks.

Quick start
-----------
1. Create and activate a Python virtual environment inside the `planner` folder:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1   # PowerShell
   # or
   .\.venv\Scripts\activate      # cmd
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Add Google OAuth credentials
   - Place your OAuth client JSON at `credentials.json` (Google Cloud console -> OAuth client ID -> Desktop app).
   - If you don't have a `token.json`, the app will open a browser to authenticate on first run.

4. Run the planner

   - Daily (default):
     ```powershell
     .\run_planner.bat --daily
     ```
   - Weekly:
     ```powershell
     .\run_planner_weekly.bat
     ```
   - Or use the PowerShell script:
     ```powershell
     .\run_planner.ps1 --daily
     ```

   - You can also run directly:
     ```powershell
     .\.venv\Scripts\python.exe plan.py --daily
     ```

5. Open the dashboard
   - Output HTML: `output/planner_dashboard.html`
   - Open it in a browser to view the AI plan sidebar and FullCalendar view.

Configuration
-------------
- Edit `config.json` to change runtime settings:
  - `model`: Ollama model name
  - `timezone`: user timezone
  - `calendar_days_ahead`: how far ahead to fetch events
  - `include_gmail`: toggle Gmail fetching
  - `user_profile`: sleep/wake times and preferences

Files of interest (quick)
------------------------
- `plan.py` — main CLI that orchestrates fetching, normalization, prompt building, generation, and rendering.
- `auth/google_auth.py` — Google OAuth helper; writes/reads `token.json`.
- `fetch/` — `calendar.py`, `tasks.py`, `gmail.py` for Google API calls.
- `core/` — `normalizer.py`, `context_builder.py`, `prompt_builder.py` for data processing and prompt assembly.
- `ai/ollama_client.py` — HTTP client to call local Ollama.
- `output/` — `calendar_formatter.py`, `formatter.py`, `template.html` and generated `planner_dashboard.html`.
- `run_planner.bat`, `run_planner.ps1`, `run_planner_weekly.bat` — convenience launchers.

Troubleshooting & tips
----------------------
- Authentication errors: remove `token.json` and re-run to re-authenticate; ensure `credentials.json` is valid.
- No events shown: inspect `output/planner_dashboard.html` and look at the embedded `events` JSON near the top; check console for FullCalendar errors.
- Ollama generation errors: ensure the Ollama server is running locally and `config.json` uses a pulled model.
- Timezone/free-block issues: check `core/normalizer.py` where free blocks are computed.

Extending / development
-----------------------
- Adjust system prompt: `prompts/system_prompt.txt`.
- Change rendering: `output/template.html` and `output/formatter.py` (controls sidebar HTML conversion).
- Add unit tests: create a `tests/` directory and add tests for normalization and parsing.

License / Security
------------------
- `credentials.json` and `token.json` contain secrets. Keep them private and do not check them into source control.

Contact / Next steps
--------------------
If you want, I can also:
- Add the detailed per-file reference (you mentioned you'll paste that),
- Add a short developer README with common grep/trace commands,
- Add a `Makefile` or `npm`-style script for cross-shell convenience.


Project root

planner/plan.py: planner/plan.py

Purpose: CLI entrypoint that wires everything together: loads config, authenticates, fetches calendar/tasks/emails concurrently, normalizes context, builds the prompt, calls the local Ollama client, and renders the HTML dashboard.
Key functions: load_config(), format_output(), render_dashboard(), build_parser(), main().
Inputs: config.json, Google credentials (via google_auth.py). CLI flags --daily, --weekly, --all.
Outputs: printed plan to stdout and planner_dashboard.html.
Where to look for bugs: failures in auth/fetch produce exceptions earlier; Ollama errors are caught and printed (see fallback behavior in main). If output HTML is missing or malformed, inspect render_dashboard() and template.html and the to_fullcalendar_events() output.
Quick checks: run .run_planner.bat --daily to reproduce; inspect printed errors and the generated planner_dashboard.html.
planner/config.json: planner/config.json

Purpose: user preferences and runtime settings (model name, timezone, calendar window, include_gmail, user profile).
Key values to tweak: model, timezone, calendar_days_ahead, max_emails, include_gmail, user_profile (workday hours).
Where to look for bugs: incorrect model name or timezone mismatch (affects parsing, free-block times). If model returns “model not found,” check model here.
planner/requirements.txt: planner/requirements.txt

Purpose: lists Python dependencies (google APIs, requests, markdown, jinja2).
Debugging tip: dependency mismatches/import errors show at runtime. Use this file to create the .venv.
planner/credentials.json: planner/credentials.json

Purpose: OAuth client credentials used by google_auth.py to obtain tokens.
Security: keep this private. If Google auth fails with credential errors, confirm this file content & validity in the Google Cloud console.
planner/token.json (generated runtime file)

Purpose: cached OAuth token created by the Google auth flow.
Security: keep private. If expired/invalid tokens cause auth failures, delete this file to re-run the OAuth flow.
planner/run_planner.bat: planner/run_planner.bat

Purpose: convenience Windows batch launcher that runs the planner with --daily by default.
Use: .run_planner.bat --daily
planner/run_planner.ps1: planner/run_planner.ps1

Purpose: PowerShell version of the launcher.
planner/run_planner_weekly.bat: planner/run_planner_weekly.bat

Purpose: convenience launcher to run plan.py --weekly.
planner/.vscode/tasks.json & planner/.vscode/settings.json: planner/.vscode/tasks.json planner/.vscode/settings.json

Purpose: VS Code tasks (Run Planner daily/weekly/all) and workspace python settings.
Debugging tip: if VS Code runs use wrong interpreter, check python.defaultInterpreterPath here.
Prompts

planner/prompts/system_prompt.txt: planner/prompts/system_prompt.txt
Purpose: system role prompt fed into the LLM; describes how to transform calendar/tasks/emails to a plan.
Debugging tip: If the AI produces unwanted formatting/behavior, adjust system prompt instructions here.
Authentication

planner/auth/google_auth.py: planner/auth/google_auth.py
Purpose: central Google OAuth helper. Handles token caching, refresh, and fresh authorization via the browser.
Key functions: get_credentials() (returns usable google.oauth2.credentials.Credentials).
Failure modes & checks:
Missing credentials.json: OAuth can’t start — error here.
Token invalid/expired: code attempts refresh; if refresh fails, it runs the interactive flow.
If local server auth fails, run the flow manually or check redirect URIs in credentials.json.
Debugging pointers: review token.json content, check network access for token refresh, inspect exceptions printed when token load fails.
Fetchers (Google API wrappers)

planner/fetch/calendar.py: planner/fetch/calendar.py

Purpose: fetch upcoming calendar events from Google Calendar and normalize into local datetimes and event dicts.
Key function: get_events(creds=None, days_ahead=14) returns list of event dicts with keys title, start, end, description, location, all_day, recurring.
Failure modes:
API permission errors — check scopes in credentials.json and google_auth.py SCOPES.
Date parsing errors — inspect start_raw/end_raw handling and timezone conversions.
Debugging: if events missing or wrong times, check how datetime.fromisoformat(...replace("Z","+00:00")) is handled and astimezone().replace(tzinfo=None) conversions.
planner/fetch/tasks.py: planner/fetch/tasks.py

Purpose: fetch Google Tasks lists and tasks, bucket into overdue, has_due_date, no_due_date.
Key function: get_tasks(creds=None, include_completed=False) returns grouped dict.
Failure modes:
Insufficient task list permissions or no tasks returned — check SCOPES.
Timezone parsing of due field — the code expects ISO format; malformed values can be skipped.
Debugging: check network/API call responses and that returned due values are parsed correctly.
planner/fetch/gmail.py: planner/fetch/gmail.py

Purpose: fetch unread Gmail messages' metadata (From, Subject, Date) and a snippet.
Key function: get_unread_emails(creds=None, max_results=20) returns list sorted by date.
Failure modes:
Gmail API quota/permissions; if headers change format, date parsing may fail.
Debugging: inspect payload returned by Gmail API, and date parsing logic using %a, %d %b %Y %H:%M:%S %z.
Core normalization & context

planner/core/normalizer.py: planner/core/normalizer.py

Purpose: take raw events/tasks/emails and produce normalized day & week contexts the rest of the app consumes. Handles:
Filtering events for today/this week
Finding free blocks (workday windows)
Detecting conflicts (overlapping events)
Tagging events with matched tasks
Bucket emails by recency
Key functions: _filter_today(), _filter_week(), _find_free_blocks(), _find_conflicts(), _tag_events_with_tasks(), _bucket_emails(), normalize().
Inputs: lists of dicts from fetchers.
Outputs: (day_context, week_context) where day_context contains events, free_blocks, conflicts, tasks_due_today, etc.; week_context contains events_by_day, tasks_this_week, and email buckets.
Failure modes and where to look:
Timezone issues: earlier code converted to UTC; recent edits made free-blocks local-aware. If free blocks show 4am, inspect _find_free_blocks() and timezone conversions.
Missing events in day_context: inspect _filter_today() and _coerce_event_day() which rely on date types/ISO strings.
Wrong conflict detection: check _find_conflicts() — it uses naive datetime comparisons; ensure both start and end are timezone-aware or normalized consistently.
Debugging tips: print today_events before/after conversions; test unit cases for boundary times.
planner/core/context_builder.py: planner/core/context_builder.py

Purpose: convert normalized contexts into a human-readable text block the LLM consumes. Formats events, free blocks, tasks, and emails into readable sections.
Key functions: _format_event(), _format_free_blocks(), _format_task(), _format_email(), build_context().
Failure modes: If model prompt lacks context or has malformed dates, inspect how normalize() structures the day_context and week_context since this builder assumes certain keys/formats.
planner/core/prompt_builder.py: planner/core/prompt_builder.py

Purpose: assemble system prompt + user context + dynamic context + request into the final prompt string sent to the model. Pulls system prompt and config.json.
Key functions: _load_config(), _load_system_prompt(), build_prompt().
Failure modes: if the prompt has unintended contents, verify system_prompt.txt and config.json values. Large prompts might be truncated by the model/backend — check prompt length before generating.
AI client

planner/ai/ollama_client.py: planner/ai/ollama_client.py
Purpose: thin HTTP client for a local Ollama instance. Supports streaming or non-streamed generation.
Key class: OllamaClient(base_url) with generate(prompt, model, stream) method.
Failure modes:
Connection failures: raises helpful message to start ollama serve.
Model not found: raises a message recommending ollama pull <model>.
Streaming parsing: streaming path iterates response.iter_lines() and attempts to JSON-parse chunks; non-JSON chunks are handled loosely. If generation incomplete or raises, check response status and server logs.
Debugging tips: replicate with curl against http://localhost:11434/api/generate to verify server; confirm config.json model name.
Output formatting & calendar mapping

planner/output/formatter.py: planner/output/formatter.py

Purpose: convert AI markdown output to safe HTML for the sidebar using markdown library.
Failure modes: invalid or malicious HTML injection — this is mitigated by Markdown conversion but still review format_ai_output() if unusual output appears.
planner/output/calendar_formatter.py: planner/output/calendar_formatter.py

Purpose: translate normalized contexts and the AI-generated plan text into FullCalendar-friendly event JSON. This includes:
parsing AI-generated lines for "1:30 PM – 3:00 PM Title" style entries (_parse_ai_plan_events),
converting actual calendar events/tasks into events with timestamps,
adding free-blocks as background events.
Key functions: _coerce_datetime(), _parse_ai_plan_events(), _categorize_event(), to_fullcalendar_events().
Failure modes:
Parsing AI text: the regex is heuristic — if AI uses a different time format, events will be missed or mis-parsed. Look at _parse_ai_plan_events() if plan lines don’t become calendar blocks.
Timezone conversions: coercion uses UTC then converts to local when formatting — mismatches lead to off-by-hours events. Inspect _format_datetime() and _coerce_datetime().
Short or junk titles: the code filters very short titles; adjust in the title post-processing if valid short titles are lost.
planner/output/template.html: planner/output/template.html

Purpose: Jinja2 HTML template used to render the dashboard: includes the sidebar for AI plan HTML, the FullCalendar container, CSS tweaks (wrapping event titles), tooltip code added, and FullCalendar initialization.
Key parts:
CSS customizations to allow multi-line event titles and tooltip styling.
JavaScript block that builds calendar with options: initialView, timeZone: 'local', slotMinTime, slotMaxTime, scrollTime, eventDidMount (tooltip) and eventWillUnmount.
Failure modes:
If calendar shows blank or events missing, inspect events_json injected into the template and the console for FullCalendar errors.
If event tooltips don’t appear, check eventDidMount handlers and that fc-tooltip element is created (the code attaches/remove listeners in mount/unmount).
planner/output/planner_dashboard.html (generated)

Purpose: final generated HTML file (Jinja2 template rendered with events_json and ai_plan_html). Not source-controlled (generated each run).
Debugging: inspect the embedded events JSON variable at top of the page; if it's malformed, the calendar will fail.
Misc / cache files

__pycache__ and */__pycache__/*.pyc: compiled Python bytecode files — ignore for source debugging. If you see stale behavior, delete these caches and re-run.
Practical debugging recipes (how to trace a problem)

If nothing happens when you run the planner:

Run the launcher from planner folder:
PowerShell:
Inspect console output for tracebacks. The plan.py main() prints errors from Ollama and prints the assembled prompt on failure.
Confirm planner_dashboard.html was written. If not, inspect render_dashboard() errors.
If Google data is missing or wrong:

Check google_auth.py for token errors. If tokens expired or scopes changed, delete token.json and re-run to re-authenticate.
Inspect raw fetch responses by temporarily printing results in calendar.py, tasks.py, gmail.py.
If free-blocks show at wrong hour (e.g., 4am instead of 8am):

Inspect normalizer.py _find_free_blocks() for timezone conversion and config.json workday_start. Confirm DEFAULT_WORKDAY_START or user_profile.workday_start usage.
If events show with wrong times:

Check calendar.py conversion (UTC handling) and calendar_formatter.py _coerce_datetime() and _format_datetime() pipeline.
If AI plan doesn’t produce calendar events:

Check calendar_formatter.py _parse_ai_plan_events() regex and example AI output. If AI format differs, update regex or normalize AI output in prompt_builder.py/system_prompt.txt.
If Ollama generation fails:

Check ollama_client.py exception messages: network connection or model-not-found. Ensure local Ollama server is running and the model in config.json is available.
Security notes

credentials.json and token.json contain secrets/tokens — never commit publicly. If leaked, rotate the client secret and revoke tokens.