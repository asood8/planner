"""Study-session scheduling as a small optimization problem, solved with OR-Tools CP-SAT.

Free time is cut into 15-minute units. Every possible session (a task, a starting unit, and a length from 30
minutes to max_session_minutes, inside one stretch of free time and on or before the task's last day) is a
yes/no variable. Hard rules: sessions never overlap, and each is followed by a 15-minute break (unless the free
time ends there); each day stays within max_minutes_per_day of study, counting sessions already added.
What the solver minimizes, most important first:
  1. time left unscheduled, weighted more heavily the sooner the task is due;
  2. time outside the preferred study hours;
  3. more than one session's worth of the same task on a single day (spacing work out beats cramming);
  4. the number of sessions (fewer, longer sessions);
  5. putting work off: each 15 minutes placed a day later costs a little, so sooner beats later.
The solver only decides which day each session lands on and how long it is. Afterwards, each day's sessions
are laid out from the earliest free time inside the preferred hours, most urgent task first (_pack_early). That keeps the
fine-grained time of day out of the optimization, which is what made proving an answer slow.
The greedy schedule is given to the solver as a starting hint, so the optimized answer is never worse than it.
Each session comes back with the reasons that applied, which the page shows. Without OR-Tools, or if the
solver fails, the greedy schedule (earliest free time, still within the daily limit) is used instead.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from core.logs import log_failure
from core.settings import StudyBlocks
from core.study_blocks import BREAK, MIN_SESSION_MINUTES, MIN_SLOT, allocate

try:
    from ortools.sat.python import cp_model
except ImportError:  # optional: the greedy scheduler works without it
    cp_model = None

UNIT = timedelta(minutes=15)
SOLVER_SECONDS = 2.0
SOLVER_WORKERS = 8
# Every weight is a multiple of W_DELAY; the solver's gap limit relies on that. (Task-specific delay weights,
# to put sooner deadlines on earlier days, were tried: they made proofs slower and answers worse. Within a
# day, _pack_early puts the most urgent task first instead.)
W_SHORTFALL = 1_000_000
W_URGENCY = 200_000  # added per unscheduled unit for each day the deadline is closer than a week
W_OUTSIDE_HOURS = 30_000
W_CRAMMING = 20_000
W_SESSION = 10_000
W_DELAY = 1_000  # per unit, for each day after today it's scheduled
CACHE_SIZE = 32

logger = logging.getLogger(__name__)
_cache: OrderedDict = OrderedDict()
_cache_lock = threading.Lock()

Spans = dict[int, list[tuple[datetime, datetime]]]  # candidate index -> (start, end) sessions


@dataclass(frozen=True)
class Session:
    key: str
    start: datetime
    end: datetime
    reasons: tuple[str, ...] = ()


@dataclass
class Schedule:
    sessions: list[Session]
    short_minutes: dict[str, int] = field(default_factory=dict)  # task key -> minutes that didn't fit
    method: str = "none"  # "optimized", "greedy", or "none"


def _minutes(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _due_phrase(due: date, today: date) -> str:
    days = (due - today).days
    when = "overdue" if days < 0 else "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    return f"Due {due:%a %b %d} ({when})"


def _inside_preferred(start: datetime, end: datetime, settings: StudyBlocks) -> bool:
    first = start.hour * 60 + start.minute
    return settings.preferred_start * 60 <= first and first + _minutes(start, end) <= settings.preferred_end * 60


def schedule(
    candidates: list[dict[str, Any]],
    slots: list[list[datetime]],
    settings: StudyBlocks,
    today: date,
    day_loads: dict[date, int] | None = None,
) -> Schedule:
    """Place study sessions for `candidates` (from study_blocks.study_candidates) in free `slots`.

    `day_loads` maps a day to the study minutes already added on it; they count toward the daily limit.
    The caller's slots aren't modified.
    """
    if not candidates:
        return Schedule([], {}, "none")
    day_loads = day_loads or {}
    cache_key = (
        tuple((c["key"], c["remaining"], c["due"], c["last_day"]) for c in candidates),
        tuple((start, end) for start, end in slots),
        settings,
        today,
        tuple(sorted(day_loads.items())),
        cp_model is not None,
    )
    with _cache_lock:
        if cache_key in _cache:
            _cache.move_to_end(cache_key)
            return _cache[cache_key]

    greedy = _greedy(candidates, slots, settings, day_loads)
    result = None
    if cp_model is not None:
        try:
            result = _optimize(candidates, slots, settings, today, day_loads, greedy)
        except Exception as exc:
            log_failure(logger, "The schedule optimizer failed, so the simple scheduler was used", exc)
    if result is None:
        result = _finish(candidates, greedy, settings, today, day_loads, "greedy")

    with _cache_lock:
        _cache[cache_key] = result
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return result


def _optimize(candidates, slots, settings: StudyBlocks, today: date, day_loads: dict[date, int], hint: Spans) -> Schedule | None:
    units: list[tuple[int, datetime]] = []  # (free block, start of the 15-minute unit)
    for block, (start, end) in enumerate(slots):
        units.extend((block, start + position * UNIT) for position in range(int((end - start) / UNIT)))
    if not units:
        return _finish(candidates, {}, settings, today, day_loads, "optimized")

    days = [start.date() for _, start in units]
    delay = [max(0, (day - today).days) for day in days]
    outside = [not _inside_preferred(start, start + UNIT, settings) for _, start in units]
    count = len(units)
    max_run = max(1, settings.max_session_minutes // 15)
    min_run = MIN_SESSION_MINUTES // 15
    first_unit = {start: u for u, (_, start) in enumerate(units)}
    hinted = {
        (t, first_unit.get(start), _minutes(start, end) // 15)
        for t, spans in hint.items()
        for start, end in spans
    }
    model = cp_model.CpModel()

    def fits(u: int, length: int) -> bool:
        """Units u .. u+length-1 are one unbroken stretch of free time."""
        last = u + length - 1
        return last < count and units[last][0] == units[u][0]

    covering: list[list] = [[] for _ in range(count)]  # sessions using each unit, for work or the break after
    by_day: dict[date, list] = {}
    choices = []  # (task, unit, length, variable) for every possible session
    objective = []
    for t, candidate in enumerate(candidates):
        need = -(-candidate["remaining"] // 15)
        mine = []  # (unit, length, variable)
        for u in range(count):
            if days[u] > candidate["last_day"]:
                continue
            for length in range(min(min_run, need), min(max_run, need) + 1):
                if not fits(u, length):
                    break  # longer sessions won't fit either
                var = model.new_bool_var(f"s{t}_{u}_{length}")
                model.add_hint(var, (t, u, length) in hinted)
                mine.append((u, length, var))
                choices.append((t, u, length, var))
                for v in range(u, u + length):
                    covering[v].append(var)
                if fits(u, length + 1):
                    covering[u + length].append(var)  # the break after it
                by_day.setdefault(days[u], []).append(length * var)
                # Time outside the preferred hours, and each day the work waits.
                cost = W_SESSION + sum(W_OUTSIDE_HOURS * outside[v] + W_DELAY * delay[v] for v in range(u, u + length))
                objective.append(cost * var)

        short = model.new_int_var(0, need, f"short{t}")
        if mine:
            total = sum(length * var for _, length, var in mine)
            model.add(total <= need)
            model.add(short == need - total)
        else:
            model.add(short == need)
        days_left = max(0, (candidate["due"] - today).days)
        objective.append((W_SHORTFALL + W_URGENCY * max(0, 7 - days_left)) * short)

        # Spaced practice: beyond one full session of this task in a day costs extra.
        if need > max_run:
            per_day: dict[date, list] = {}
            for u, length, var in mine:
                per_day.setdefault(days[u], []).append(length * var)
            for day, terms in per_day.items():
                over = model.new_int_var(0, need, f"over{t}_{day:%Y%m%d}")
                model.add(over >= sum(terms) - max_run)
                objective.append(W_CRAMMING * over)

    # No overlaps, and a break after each session.
    for group in covering:
        if len(group) > 1:
            model.add_at_most_one(group)

    # Daily study limit, counting sessions already added that day.
    cap_units = settings.max_minutes_per_day // 15
    for day, terms in by_day.items():
        model.add(sum(terms) <= max(0, cap_units - day_loads.get(day, 0) // 15))

    model.minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_SECONDS
    solver.parameters.num_workers = SOLVER_WORKERS
    # Probing during presolve took about a second on a normal week and made answers worse within the time
    # limit (measured), so skip it.
    solver.parameters.cp_model_probing_level = 0
    # Every cost is a multiple of W_DELAY, so an answer within W_DELAY - 1 of the bound is the best there is;
    # stopping there skips proving what's already settled.
    solver.parameters.absolute_gap_limit = W_DELAY - 1
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("The schedule optimizer found no answer (%s); using the simple scheduler.", solver.status_name(status))
        return None
    if status == cp_model.FEASIBLE:
        logger.info("The schedule optimizer stopped at its time limit with a good, possibly not best, answer.")

    placed: Spans = {}
    for t, u, length, var in choices:
        if solver.boolean_value(var):
            placed.setdefault(t, []).append((units[u][1], units[u][1] + length * UNIT))
    return _finish(candidates, _pack_early(placed, slots, settings), settings, today, day_loads, "optimized")


def _pack_early(placed: Spans, slots: list[list[datetime]], settings: StudyBlocks) -> Spans:
    """Settle the time of day: each day's sessions inside the preferred hours are laid out from the earliest free
    time, most urgent task first (candidates are in deadline order). Sessions outside the preferred hours stay
    where the solver put them.

    Nothing the solver weighed changes (the day, the lengths, time outside the preferred hours), so the answer
    stays optimal, and the layout doesn't depend on which of several equally good answers the solver found. If
    the urgent-first order doesn't fit, the solver's own order is used: laid out earliest-first it always fits,
    because each session's original spot is still free when its turn comes.
    """
    blocks_by_day: dict[date, list[tuple[datetime, datetime]]] = {}
    for first, last in slots:
        blocks_by_day.setdefault(first.date(), []).append((first, last))
    sessions_by_day: dict[date, list[tuple[datetime, datetime, int]]] = {}
    for t, spans in placed.items():
        for start, end in spans:
            sessions_by_day.setdefault(start.date(), []).append((start, end, t))

    packed: Spans = {}
    for day, sessions in sessions_by_day.items():
        blocks = sorted(blocks_by_day.get(day, []))
        fixed = [session for session in sessions if not _inside_preferred(session[0], session[1], settings)]
        movable = [session for session in sessions if _inside_preferred(session[0], session[1], settings)]
        by_urgency = sorted(movable, key=lambda session: (session[2], session[0]))
        laid_out = (
            _lay_out(by_urgency, blocks, fixed, settings)
            or _lay_out(sorted(movable), blocks, fixed, settings)
            or movable
        )
        for start, end, t in fixed + laid_out:
            packed.setdefault(t, []).append((start, end))
    for spans in packed.values():
        spans.sort()
    return packed


def _lay_out(sessions, blocks, fixed, settings: StudyBlocks) -> list[tuple[datetime, datetime, int]] | None:
    """Each session at the earliest start that fits, in the given order; None if one doesn't fit."""
    taken = [(start, end) for start, end, _ in fixed]
    result = []
    for start, end, t in sessions:
        new_start = _earliest_start(end - start, blocks, taken, settings, start)
        if new_start is None:
            return None
        result.append((new_start, new_start + (end - start), t))
        taken.append((new_start, new_start + (end - start)))
    return result


def _earliest_start(length: timedelta, blocks, taken, settings: StudyBlocks, on_day: datetime) -> datetime | None:
    """The earliest start inside the preferred hours where a session of `length` fits in a free block without
    touching `taken` sessions (keeping a break between sessions in the same block), or None."""
    preferred = on_day.replace(hour=settings.preferred_start, minute=0, second=0, microsecond=0)
    for first, last in blocks:
        in_block = [(start, end) for start, end in taken if first <= start < last]
        for start in sorted({max(first, preferred)} | {end + BREAK for _, end in in_block}):
            end = start + length
            if start < first or end > last or not _inside_preferred(start, end, settings):
                continue
            if all(end + BREAK <= other_start or other_end + BREAK <= start for other_start, other_end in in_block):
                return start
    return None


def _greedy(candidates, slots, settings: StudyBlocks, day_loads: dict[date, int]) -> Spans:
    """Earliest deadline first, each into the earliest free time, still within the daily study limit."""
    work = [list(slot) for slot in slots]  # allocate() consumes slots; keep the caller's intact
    days = [start.date() for start, _ in slots]
    left: dict[date, int] = {}  # day -> study minutes still allowed under the daily limit
    placed: Spans = {}
    for t, candidate in enumerate(candidates):
        remaining = candidate["remaining"]
        spans = []
        for day, slot in zip(days, work):
            if day > candidate["last_day"] or remaining <= 0:
                break
            budget = min(remaining, left.setdefault(day, settings.max_minutes_per_day - day_loads.get(day, 0)))
            if budget < min(MIN_SESSION_MINUTES, remaining):
                continue
            taken = allocate([slot], budget, day, settings.max_session_minutes)
            minutes = sum(_minutes(start, end) for start, end in taken)
            left[day] -= minutes
            remaining -= minutes
            spans.extend(taken)
        placed[t] = spans
    return placed


def _finish(candidates, placed: Spans, settings: StudyBlocks, today: date, day_loads: dict[date, int], method: str) -> Schedule:
    """Sessions with the reasons that applied, plus the minutes each task couldn't get."""
    day_totals = dict(day_loads)
    for spans in placed.values():
        for start, end in spans:
            day_totals[start.date()] = day_totals.get(start.date(), 0) + _minutes(start, end)

    sessions, short = [], {}
    for t, candidate in enumerate(candidates):
        spans = placed.get(t, [])
        missing = candidate["remaining"] - sum(_minutes(start, end) for start, end in spans)
        if missing > 0:
            short[candidate["key"]] = missing
        spread = len({start.date() for start, _ in spans})
        for start, end in spans:
            reasons = [_due_phrase(candidate["due"], today)]
            if method == "greedy":
                reasons.append("The earliest free time before it's due")
            else:
                if spread > 1:
                    reasons.append(f"Split across {spread} days so it isn't crammed")
                if _inside_preferred(start, end, settings):
                    reasons.append("Inside your preferred study hours")
                else:
                    reasons.append("Outside your preferred study hours, which were already full")
            if day_totals.get(start.date(), 0) >= settings.max_minutes_per_day:
                reasons.append(f"{start:%A} is at your daily study limit")
            sessions.append(Session(candidate["key"], start, end, tuple(reasons)))
    sessions.sort(key=lambda session: session.start)
    return Schedule(sessions, short, method)


def remaining_slots(slots: list[list[datetime]], sessions: list[Session]) -> list[list[datetime]]:
    """Free slots with the scheduled sessions cut out (for placing reply reminders afterwards)."""
    result = []
    for slot_start, slot_end in slots:
        pieces = [[slot_start, slot_end]]
        for session in sessions:
            cut = []
            for start, end in pieces:
                if session.end <= start or session.start >= end:
                    cut.append([start, end])
                    continue
                if session.start > start:
                    cut.append([start, session.start])
                if session.end < end:
                    cut.append([session.end, end])
            pieces = cut
        result.extend(piece for piece in pieces if piece[1] - piece[0] >= MIN_SLOT)
    return result
