# Local AI Planner

I built this to plan my own weeks as a student. It pulls in Google Calendar, Google Tasks and unread Gmail, works out when you should actually work on what's due, and has a language model running locally through Ollama write a daily or weekly plan. Nothing is sent to a cloud AI service, and everything it saves stays on your machine.

![The week view: classes, events, and tasks marked in highlighter colors, dashed suggested study and exam-review sessions, a red outline where two events overlap, and a sidebar with this week's warnings, sessions to check in, and the day's plan](docs/screenshots/week.png)

<sub>Screenshots use made-up sample data.</sub>

## What it does

- Reads your Google Calendar, Google Tasks, Gmail, and calendar feeds like Canvas.
- Schedules study time before deadlines with a constraint solver, inside the hours you like to study and under a daily cap.
- Spaces out exam review over the days before an exam instead of leaving it for the night before.
- Learns how long your tasks really take.
- Warns you when the week is going to be too tight.
- Has a local model write the day's plan and put it on the calendar.

## Requirements

- Python 3.11 or newer
- [Ollama](https://ollama.com) with a model pulled (the default config uses `phi4-mini`, so `ollama pull phi4-mini`)
- A Google Cloud project with the Calendar, Tasks and Gmail APIs turned on

It runs on Windows, macOS and Linux. The `.bat` launchers and the notifications only work on Windows; on anything else, run the Python commands directly.

## Setup

1. `python -m venv .venv`
2. `.\.venv\Scripts\Activate.ps1` on Windows, or `source .venv/bin/activate` on macOS and Linux
3. `pip install -r requirements.txt`
4. In the Google Cloud Console, create an OAuth client ID of type "Desktop app", download it, and save it as `credentials.json` in the project folder. Until the app is verified, you'll also need to add your own Google account as a test user on the consent screen.
5. Copy `config.example.json` to `config.json` and edit it. Set `timezone` (for example `America/New_York`), or leave it empty to use your computer's. If something in the config is invalid, the planner tells you which setting is wrong and why, and uses the defaults until you fix it.

The first time you run it, a browser tab opens so you can sign in to Google. (The web app will just keep loading until you finish.) After that the token is saved in `token.json` and you won't be asked again.

Every Google permission it asks for is read-only, so it can't change anything in your account.

## Running it

To generate a plan from the command line:

    python plan.py --daily      # or --weekly, or --all (the default)

This fetches everything, asks Ollama for a plan, and writes it to `output/planner_dashboard.html`. On Windows, `run_planner.bat` does the same thing and starts Ollama for you if it isn't already running.

Most of the time you'll want the web app instead:

    python server.py            # then open http://127.0.0.1:5000

On Windows, `run_server.bat` starts it (and Ollama, if needed) and opens the page for you.

## Using the dashboard

### Plans

Click **Generate plan** and the plan streams into the sidebar as the model writes it. When it's done, its time blocks show up on the calendar. You can plan today, the week, or both. Plans are saved, and older ones are under **Earlier plans**.

### Adding things

Type something like `gym tomorrow 5pm` or `dentist fri 2:30-3:30pm` into the box at the top of the sidebar and press Enter. Dates, times, ranges and durations (`for 2h`) are parsed directly. Anything it can't parse goes to the model.

For longer notes, write them in the Note box and click **Add notes to calendar**. The model turns them into events and avoids times you're already busy. The standing note is for things that don't change, like when you usually go to the gym, and it's included every time.

### Study sessions

Tasks due in the next three days get suggested work sessions in your free time. A task counts as an hour unless its title or notes say otherwise (`~2h`, `est 90m`).

The sessions are placed by Google's OR-Tools CP-SAT solver. It has a few hard rules:

- sessions are between 30 minutes and `max_session_minutes` long, with a 15-minute break after each one
- no more than `max_minutes_per_day` of studying in a day, counting sessions you've already accepted
- nothing is scheduled after its deadline

Within those rules it tries, in this order, to fit all the work in (nearest deadlines first if there isn't room for everything), stay inside your `preferred_hours`, spread big tasks over a few days, use fewer and longer sessions, and get things done sooner rather than later.

Click a suggested session to see why it ended up there, for example "Due Tue Sep 15 (tomorrow). Split across 2 days so it isn't crammed. Inside your preferred study hours." If there isn't enough free time, the sidebar tells you how far short you are. All of this is configured under `study_blocks` in `config.json`. If OR-Tools isn't installed, it falls back to a simpler scheduler that takes the earliest free time.

### Learning how long things take

When you mark a task done, it asks how long it took, filled in with the time from the sessions you'd started. After three finished tasks it starts comparing how long things took with what it planned. If the tasks in one of your lists keep taking 1.5 times as long as you estimated, it starts planning 1.5 times as much time for them.

It learns each list separately, uses your overall average for lists without enough history yet, and won't overreact to one unusual task. You can see what it's learned under **How long things take** in the sidebar, or turn it off with `"learn_estimates": false`.

### Check-ins

Once a session you accepted is over, it shows up under **Did these happen?** (you can also click it on the calendar). If you skipped it, mark it skipped and that time gets suggested again. If you never answer, it counts as done.

### Exams

Anything on your calendar that looks like an exam (midterm, final, quiz, test) gets review sessions spread over the days before it, finishing the day before. It assumes four hours of review for an exam and one for a quiz, unless the event says otherwise, like `~6h`. The settings are under `exam_prep`; set `days_before` to 0 to turn it off.

### The week ahead, and wrapping up the day

The sidebar warns you about packed days coming up, and about work due later in the week that won't fit in the time you have left.

From 6 PM (change it with `user_profile.review_hour`) there's a **Wrapping up today** section: what you finished, how your sessions went, what's still open, and what tomorrow starts with. You don't have to move anything yourself. Whatever didn't get done is scheduled again.

### Email

The local model reads unread emails that mention a deadline or ask for a reply, and only reads each one once. Deadlines show up as suggested all-day items, and reply requests as a suggested 15-minute block.

### Marking tasks done

Click a task on the calendar to mark it done. This only hides it in the planner (Google Tasks isn't touched) and removes any of its sessions that haven't started. You can undo it from **Marked done**.

### Reading the calendar

Each color is a kind of thing: classes, events, tasks, things you added, and the AI plan. Dashed boxes are suggestions. Click one to accept or dismiss it, or drag it to a better time. Overlapping events get a red outline.

The dots at the bottom of the sidebar show whether each data source loaded and whether Ollama is running, and you can switch models there too. Google data is cached for five minutes; click **Refresh** to fetch it again.

<p align="center"><img src="docs/screenshots/phone.png" width="320" alt="The sidebar on a phone-sized screen in the evening: this week's warnings, sessions to check in, the end-of-day review with a task still open, and the day's plan"></p>

## Canvas and other calendar feeds

You can add read-only calendar links in `config.json` under `ical_feeds`:

    "ical_feeds": [
      {"name": "Canvas", "url": "https://canvas.example.edu/feeds/calendars/user_XXXX.ics"}
    ]

In Canvas the link is under Calendar → Calendar Feed. For a Google calendar, use the "Secret address in iCal format" from that calendar's settings. Assignments come in as tasks and get study sessions; everything else comes in as events. If the same calendar is also in your Google Calendar, the duplicates are removed.

Anyone with one of these links can see that calendar, so keep them only in `config.json`, which is gitignored.

## Notifications (Windows only)

Run `schedule_morning_plan.bat` once to get a plan every morning at 7:00, or pass a different time, like `schedule_morning_plan.bat 06:30`. Each morning it writes the plan and sends a notification with what's due, what's next, and any sessions you still need to check in. Clicking the notification opens the web app if it's running, or the saved dashboard if it isn't. To remove it, run `schtasks /Delete /TN "Planner morning plan" /F`.

`schedule_evening_review.bat` works the same way for a 9 PM notification with sessions to check in, open tasks, and how tomorrow starts. It doesn't need Ollama. To remove it, run `schtasks /Delete /TN "Planner evening review" /F`.

## Your data

Everything it saves (events you added, dismissed suggestions, old plans, email scan results, finished tasks and how long they took, and check-ins) is plain JSON in the `data/` folder. None of it is sent anywhere. Logs go to `data/planner.log`, so if a morning plan didn't show up, look there first.

## Tests

    python -m unittest discover -s tests

None of the tests need Google or Ollama. They cover the scheduler, the parsers, time zone handling, and the web app's routes, using fake data.

## License

MIT. See [LICENSE](LICENSE).
