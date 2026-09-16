# Local AI Planner

A planner that reads your Google Calendar, Google Tasks, and unread Gmail, decides when you should work on
what's due, and writes a daily or weekly plan using a language model running on your own machine. No cloud AI
service is involved, and everything the planner creates stays in a folder on your computer.

![The week view: classes, events, and tasks marked in highlighter colors, dashed suggested study and exam-review sessions, a red outline where two events overlap, and a sidebar with this week's warnings, sessions to check in, and the day's plan](docs/screenshots/week.png)

<sub>Screenshots use made-up sample data.</sub>

## What it does

- Collects your week from Google Calendar, Google Tasks, unread Gmail, and read-only calendar feeds such as Canvas.
- Suggests when to work on each task, using a constraint solver that respects your deadlines, your preferred
  study hours, and a daily limit on how much you'll study.
- Spreads exam review over the days before an exam instead of leaving it to the night before.
- Learns how long your tasks actually take and adjusts its future estimates.
- Warns you when a day is overloaded, or when the work due later this week won't fit in the time you have left.
- Writes the plan itself with your local model, and draws it on the calendar.

## Requirements

- Python 3.11 or newer.
- [Ollama](https://ollama.com), running, with a model pulled (for example `ollama pull phi4-mini`).
- A Google Cloud project with the Calendar, Tasks, and Gmail APIs enabled.

The planner itself runs on Windows, macOS, and Linux. The `.bat` launchers and the desktop notifications are
Windows-only; everywhere else, run the Python commands directly.

## Setup

1. `python -m venv .venv`
2. `.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (macOS and Linux)
3. `pip install -r requirements.txt`
4. In the Google Cloud Console, create OAuth credentials of type "Desktop app" and save the download as
   `credentials.json` in the project root. While your app is unverified, add your own account as a test user on
   the OAuth consent screen.
5. Copy `config.example.json` to `config.json` and fill in your details. Set `timezone` to your own zone, for
   example `America/New_York`, or leave it blank to use your computer's. If a setting has a value the planner
   can't use, it names the setting and the reason, shows it at the top of the sidebar, and carries on with the
   defaults until you fix it.

The first run opens a browser window for Google's consent screen. With the web app, the page keeps loading until
you finish signing in. This happens once; after that the token is cached in `token.json`.

All four Google scopes are read-only. The planner never creates, edits, or deletes anything in your Google
account.

## Running it

**A plan from the command line.** Fetches your data, asks Ollama for a plan, and writes
`output/planner_dashboard.html`:

    python plan.py --daily      # or --weekly, or --all (the default with no flag)

On Windows, `run_planner.bat` does the same through `.venv`, and starts Ollama first if it isn't running.

**The web app.** A dashboard served on your machine, with everything below:

    python server.py            # then open http://127.0.0.1:5000

On Windows, `run_server.bat` starts Ollama if needed and opens the page for you.

## Inside the dashboard

**Plans.** **Generate plan** streams a plan into the sidebar as the model writes it, then draws its time blocks
on the calendar. Choose Today, This week, or Both. Plans are saved, so the most recent one survives a restart,
and **Earlier plans** brings back previous ones.

**Notes and quick add.** Write in the Note box and choose **Add notes to calendar** to turn plain sentences into
events that avoid times you're already busy. A standing note is kept alongside it and included every time, which
is a good place for things like a recurring gym slot. For a single event, type it in the box at the top of the
sidebar — `gym tomorrow 5pm` or `dentist fri 2:30-3:30pm` — and press Enter. Dates, times, ranges, and durations
such as `for 2h` are understood without the model; anything else is handed to it.

**Study sessions.** Tasks due within the next three days get suggested work sessions in your free time. A task is
assumed to take an hour unless its title or notes say otherwise, with a note like `~2h` or `est 90m`. Sessions
are placed by Google's OR-Tools CP-SAT solver, which treats your week as a scheduling problem:

- **Rules it never breaks:** sessions run from 30 minutes up to `max_session_minutes`, each is followed by a
  15-minute break, no day holds more than `max_minutes_per_day` of study (counting sessions you've already
  accepted), and nothing is scheduled after a deadline.
- **What it aims for, in order:** fit all the work in, favouring the nearest deadlines when time is short; stay
  within your `preferred_hours`; spread a long task across several days rather than cramming it into one; use
  fewer, longer sessions; and do the work sooner rather than later. Within each day, sessions start as early as
  your calendar and preferred hours allow, most urgent task first.
- Click a session to see the reasoning, for example "Due Tue Sep 15 (tomorrow). Split across 2 days so it isn't
  crammed. Inside your preferred study hours."
- When there isn't enough free time, the sidebar says so and by how much. If OR-Tools isn't available, a simpler
  earliest-free-time scheduler takes over.
- The numbers above live in `config.json` under `study_blocks`.

**Estimates that learn.** When you mark a task done, the planner adds up the sessions you'd started for it and
asks **How long did it take?** with that total filled in. After three measured tasks it compares the time they
took against what was planned and adjusts future estimates. If tasks in one of your lists consistently take half
again as long as expected, it starts planning that much time for them. Each list is learned separately, lists
without enough history fall back to your overall record, and small samples are pulled toward no adjustment so a
single unusual task can't distort things. **How long things take** in the sidebar shows what it has worked out.
Set `learn_estimates` to `false` to switch this off.

**Check-ins.** Once a session you accepted has passed, **Did these happen?** asks whether you did it; you can
also click the session on the calendar. Marking one as skipped returns its time to the suggestions rather than
counting it as work done. Sessions you never answer still count.

**Exam prep.** Calendar events that look like exams — midterm, final, quiz, test — get review sessions spread
across the days beforehand, finishing the day before the exam. An exam is assumed to need four hours of review
and a quiz one hour, unless the event says otherwise with something like `~6h`. This is configured under
`exam_prep`, and `"days_before": 0` turns it off.

**Coming up this week.** The sidebar flags days packed with events, and warns when the work due later in the week
won't fit in the study time left before it.

**Wrapping up today.** From 6 PM, which you can change with `user_profile.review_hour`, the sidebar reviews the
day: what you finished, how your sessions went, what's still open with a **Mark done** link beside it, and how
tomorrow begins. Nothing needs to be carried over by hand; unfinished work is suggested again on its own.

**Email deadlines.** Your local model reads unread mail that mentions a deadline or asks for a reply, once per
message. Deadlines become suggested all-day entries and replies become suggested 15-minute blocks.

**Marking tasks done.** Click a task on the calendar to mark it done. It's only hidden inside the planner, since
Google Tasks is never modified, and any of its sessions that haven't started are removed. **Marked done** in the
sidebar undoes it.

**Reading the calendar.** Colors mark what a thing is: classes, events, tasks, items you added, and the AI plan.
Suggestions have a dashed border — click one to accept or dismiss it, or drag it to a time that suits you better.
Overlapping events get a red outline, and a line marks the current time. At the bottom of the sidebar, dots show
whether each source loaded and whether Ollama is running, next to a picker for which installed model to use.
Google data is cached for five minutes, and **Refresh** fetches it again.

<p align="center"><img src="docs/screenshots/phone.png" width="320" alt="The sidebar on a phone-sized screen in the evening: this week's warnings, sessions to check in, the end-of-day review with a task still open, and the day's plan"></p>

## Canvas and other calendar feeds

Read-only calendar links go in `config.json` under `ical_feeds`:

    "ical_feeds": [
      {"name": "Canvas", "url": "https://canvas.example.edu/feeds/calendars/user_XXXX.ics"}
    ]

In Canvas the address is under Calendar → Calendar Feed. For a Google calendar, it's the "Secret address in iCal
format" in that calendar's settings. Assignments arrive as tasks and get study sessions like any other; the rest
appear as events. If you subscribe to the same calendar in Google Calendar as well, the duplicates are left out.
These links grant access to the calendar, so keep them in `config.json`, which is never committed.

## Daily notifications (Windows)

**Morning plan.** Run `schedule_morning_plan.bat` once to create a daily task at 7:00, or pass a time such as
`schedule_morning_plan.bat 06:30`. Each morning it writes the plan and shows a notification with what's due,
what's next, and any sessions waiting to be checked in. Clicking it opens the web app if it's running, and the
saved dashboard otherwise. Remove it with `schtasks /Delete /TN "Planner morning plan" /F`.

**Evening review.** Run `schedule_evening_review.bat` once, at 9:00 PM by default, for a notification listing the
sessions to check in, the tasks still open, and how tomorrow starts. It doesn't need Ollama. Remove it with
`schtasks /Delete /TN "Planner evening review" /F`.

## Where your data lives

Everything the planner saves — events you added, dismissed suggestions, plan history, email scan results, tasks
marked done with how long they took, and session check-ins — is stored as plain JSON in `data/`. None of it goes
back to Google or anywhere else. Both the web app and the scheduled runs log to `data/planner.log`, with the
reason for any failure, which is the first place to look if a morning plan doesn't appear.

## Tests

    python -m unittest discover -s tests

The suite needs neither Google nor Ollama; it covers the scheduler, the parsers, the time handling, and the
web app's routes against stand-in data.

## License

MIT — see [LICENSE](LICENSE).
