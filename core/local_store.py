"""Small JSON files under data/ (gitignored): saved events, plan history, email scan cache, dismissals.

The CLI (e.g. the scheduled morning plan) and the web server can run at the same time, so every
read-modify-write goes through locked(), which holds an OS file lock that works across processes as
well as threads. Readers don't need the lock, because writes replace files atomically.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# PLANNER_DATA_DIR lets tests (and other processes they start) use a temporary directory.
DATA_DIR = Path(os.environ.get("PLANNER_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
LOCK_TIMEOUT = 10.0
_POLL_SECONDS = 0.05
_REPLACE_ATTEMPTS = 20

_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


class StoreBusy(TimeoutError):
    """Another thread or process is holding a data/ lock."""

    def __init__(self, name: str):
        super().__init__(f"data/{name} is busy; another planner process is using it")
        self.name = name


def data_path(name: str) -> Path:
    """Resolved at call time so tests can point DATA_DIR at a temporary directory."""
    return DATA_DIR / name


def _thread_lock(name: str) -> threading.Lock:
    with _thread_locks_guard:
        return _thread_locks.setdefault(name, threading.Lock())


def _try_os_lock(handle) -> bool:
    try:
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _os_unlock(handle) -> None:
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def locked(name: str, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """Hold the exclusive lock for data/<name> across threads and processes.

    Raises StoreBusy if it isn't free within `timeout` seconds (0 means don't wait).
    """
    deadline = time.monotonic() + timeout
    thread_lock = _thread_lock(name)
    acquired = thread_lock.acquire(blocking=False) if timeout <= 0 else thread_lock.acquire(timeout=timeout)
    if not acquired:
        raise StoreBusy(name)
    try:
        lock_path = data_path(name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "a+b") as handle:
            while not _try_os_lock(handle):
                if time.monotonic() >= deadline:
                    raise StoreBusy(name)
                time.sleep(_POLL_SECONDS)
            try:
                yield
            finally:
                _os_unlock(handle)
    finally:
        thread_lock.release()


def read_json(path: Path, default: Any) -> Any:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            # Windows briefly refuses to open a file while another process replaces it.
            if attempt == _REPLACE_ATTEMPTS - 1:
                return default
            time.sleep(_POLL_SECONDS)
        except (OSError, ValueError):
            return default
    return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError:
            # Windows can't replace a file that another process has open for reading; retry briefly.
            if attempt == _REPLACE_ATTEMPTS - 1:
                temp_path.unlink(missing_ok=True)
                raise
            time.sleep(_POLL_SECONDS)
