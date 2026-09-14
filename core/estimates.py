"""Learned time estimates: how long tasks really take compared with what the planner assumed.

Estimates start from "~2h" / "est 90m" in a task's title or notes, or the default. When a task is marked
done, the planner records that estimate next to the time actually spent: the study sessions added for it
that had started by then, which the user can correct in the "How long did it take?" prompt. From those
pairs it learns a multiplier per task list ("School tasks take 1.4x what was planned"), falling back to one
across all lists. Estimates only change after MIN_SAMPLES finished tasks; small samples are pulled toward
1x by PRIOR_WEIGHT pseudo-samples so one odd task can't swing them; and the result stays within 0.5x-2.5x.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.settings import StudyBlocks

ESTIMATE_RE = re.compile(
    r"(?:~|\best(?:imate)?\b[:\s]*)\s*(\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?)\b",
    re.IGNORECASE,
)
MIN_SAMPLES = 3
PRIOR_WEIGHT = 2
MIN_MULTIPLIER = 0.5
MAX_MULTIPLIER = 2.5
ROUND_TO = 15


def parse_estimate(task: dict[str, Any]) -> int | None:
    """Minutes from "~2h", "est 90m", or "estimate: 1.5 hours" in the title or notes, if any."""
    for text in (task.get("title"), task.get("notes")):
        match = ESTIMATE_RE.search(str(text or ""))
        if match:
            amount = float(match.group(1))
            minutes = amount * 60 if match.group(2).lower().startswith("h") else amount
            return max(15, round(minutes))
    return None


def estimate_minutes(task: dict[str, Any], default_minutes: int) -> int:
    """The task's own estimate, else the default (no learning)."""
    parsed = parse_estimate(task)
    return parsed if parsed is not None else default_minutes


def format_minutes(minutes: int) -> str:
    hours, rest = divmod(int(minutes), 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    return f"{hours} h" if hours else f"{rest} min"


@dataclass(frozen=True)
class Calibration:
    """Learned multipliers: by_list[name] = (multiplier, samples) for lists with enough samples."""

    by_list: dict[str, tuple[float, int]] = field(default_factory=dict)
    overall: tuple[float, int] = (1.0, 0)

    def multiplier_for(self, list_name: str) -> tuple[float, str | None]:
        """(multiplier, what it was learned from); the source is None when there's nothing to learn from yet."""
        if list_name in self.by_list:
            return self.by_list[list_name][0], f"{list_name or 'Unlisted'} tasks"
        multiplier, samples = self.overall
        if samples >= MIN_SAMPLES:
            return multiplier, "your tasks"
        return 1.0, None


def _ratios(done_entries: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """(task list, actual / estimate) for finished tasks that have both numbers."""
    ratios = []
    for entry in done_entries:
        estimate, actual = entry.get("estimate"), entry.get("actual")
        if isinstance(estimate, (int, float)) and isinstance(actual, (int, float)) and estimate > 0 and actual > 0:
            ratios.append((str(entry.get("list") or ""), actual / estimate))
    return ratios


def _multiplier(ratios: list[float]) -> float:
    """Geometric mean of the ratios, pulled toward 1x by PRIOR_WEIGHT pseudo-samples, then clamped."""
    log_mean = sum(math.log(ratio) for ratio in ratios) / (len(ratios) + PRIOR_WEIGHT)
    return min(MAX_MULTIPLIER, max(MIN_MULTIPLIER, math.exp(log_mean)))


def learn(done_entries: list[dict[str, Any]]) -> Calibration:
    points = _ratios(done_entries)
    by_list = {}
    for name in sorted({name for name, _ in points}):
        ratios = [ratio for list_name, ratio in points if list_name == name]
        if len(ratios) >= MIN_SAMPLES:
            by_list[name] = (_multiplier(ratios), len(ratios))
    overall = (_multiplier([ratio for _, ratio in points]) if points else 1.0, len(points))
    return Calibration(by_list=by_list, overall=overall)


@dataclass(frozen=True)
class Estimate:
    minutes: int  # what the scheduler plans for
    base: int  # before learning: the task's own estimate, or the default
    from_task: bool
    multiplier: float = 1.0
    learned_from: str | None = None

    def note(self) -> str:
        total = f"About {format_minutes(self.minutes)} in total"
        source = f"you estimated {format_minutes(self.base)}" if self.from_task else f"the default is {format_minutes(self.base)}"
        if self.learned_from and self.minutes != self.base:
            return f"{total}: {source}, adjusted because {self.learned_from} have taken {self.multiplier:.1f}× as long as planned"
        return f"{total} ({source})"


def estimate_for(task: dict[str, Any], settings: StudyBlocks, calibration: Calibration | None) -> Estimate:
    parsed = parse_estimate(task)
    base, from_task = (parsed, True) if parsed is not None else (settings.default_minutes, False)
    if not settings.learn_estimates or calibration is None:
        return Estimate(base, base, from_task)
    multiplier, learned_from = calibration.multiplier_for(str(task.get("list") or ""))
    if learned_from is None:
        return Estimate(base, base, from_task)
    minutes = max(ROUND_TO, ROUND_TO * round(base * multiplier / ROUND_TO))
    return Estimate(minutes, base, from_task, multiplier, learned_from)


def measure_actual(task_key: str, calendar_events: list[dict[str, Any]], now: datetime) -> int:
    """Minutes of the task's study sessions (saved events with ref study:<key>) that had started by `now`;
    a session in progress counts up to now, and one checked in as skipped doesn't count."""
    ref = f"study:{task_key}"
    total = 0
    for event in calendar_events:
        start, end = event.get("start"), event.get("end")
        if event.get("ref") != ref or event.get("status") == "skipped":
            continue
        if not isinstance(start, datetime) or not isinstance(end, datetime) or start >= now:
            continue
        total += int((min(end, now) - start).total_seconds() // 60)
    return total


def describe(calibration: Calibration) -> list[str]:
    """Plain-language summaries for the sidebar."""
    lines = [
        f"{name or 'Unlisted'} tasks have taken {multiplier:.1f}× as long as planned ({samples} finished)"
        for name, (multiplier, samples) in calibration.by_list.items()
    ]
    multiplier, samples = calibration.overall
    covered_by_one_list = len(calibration.by_list) == 1 and next(iter(calibration.by_list.values()))[1] == samples
    if samples >= MIN_SAMPLES:
        if not covered_by_one_list:
            lines.append(f"All tasks: {multiplier:.1f}× as long as planned ({samples} finished)")
    elif samples:
        plural = "s" if samples != 1 else ""
        lines.append(f"{samples} finished task{plural} measured so far. Estimates start adjusting after {MIN_SAMPLES}.")
    return lines
