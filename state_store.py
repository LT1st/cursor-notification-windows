"""
Persistent task state for Cursor notification panel.
Uses atomic JSON replace + lock file for concurrent hook writers on Windows.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

DEFAULT_RELATIVE_DIR = os.path.join("cursor_notification", "data")


def default_state_path() -> str:
    custom = os.environ.get("CURSOR_NOTIFICATION_STATE")
    if custom:
        return os.path.expandvars(custom)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, DEFAULT_RELATIVE_DIR, "state.json")


def default_lock_path(state_path: str) -> str:
    return state_path + ".lock"


@dataclass
class TaskRecord:
    sessionId: str
    taskId: str
    title: str
    status: str
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    lastMessage: str = ""
    updatedAt: str = ""

    def key(self) -> str:
        return f"{self.sessionId}::{self.taskId}"


def _iso_now() -> str:
    # ISO with local offset awareness via UTC Z is fine for display
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _acquire_lock(lock_path: str, timeout_s: float = 5.0, poll: float = 0.02) -> int:
    """Create exclusive lock file; returns fd to close after release."""
    deadline = time.time() + timeout_s
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            return fd
        except FileExistsError:
            if time.time() > deadline:
                raise TimeoutError(f"Could not acquire lock: {lock_path}")
            time.sleep(poll)


def _release_lock(fd: int, lock_path: str) -> None:
    try:
        os.close(fd)
    finally:
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def load_state_raw(state_path: str) -> Dict[str, Any]:
    if not os.path.isfile(state_path):
        return {"version": 1, "tasks": [], "notifiedTerminal": {}}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state_raw(state_path: str, data: Dict[str, Any]) -> None:
    _ensure_parent(state_path)
    dir_name = os.path.dirname(os.path.abspath(state_path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".state_", suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as wf:
            json.dump(data, wf, ensure_ascii=False, indent=2)
            wf.write("\n")
        os.replace(tmp_path, state_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def tasks_from_state(data: Dict[str, Any]) -> List[TaskRecord]:
    out: List[TaskRecord] = []
    for row in data.get("tasks") or []:
        try:
            out.append(
                TaskRecord(
                    sessionId=str(row.get("sessionId") or ""),
                    taskId=str(row.get("taskId") or ""),
                    title=str(row.get("title") or ""),
                    status=str(row.get("status") or "UNKNOWN"),
                    startedAt=row.get("startedAt"),
                    finishedAt=row.get("finishedAt"),
                    lastMessage=str(row.get("lastMessage") or ""),
                    updatedAt=str(row.get("updatedAt") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def merge_task_update(
    state_path: str,
    session_id: str,
    task_id: str,
    title: str,
    status: str,
    last_message: str = "",
) -> tuple[TaskRecord, bool, Optional[str]]:
    """
    Merge one task update. Returns (record, should_notify, previous_status or None).
    should_notify is True when transitioning to FINISHED or ERROR and not yet notified.
    """
    lock_path = default_lock_path(state_path)
    fd = _acquire_lock(lock_path)
    try:
        data = load_state_raw(state_path)
        tasks = {t.key(): t for t in tasks_from_state(data)}
        key = f"{session_id}::{task_id}"
        now = _iso_now()
        prev = tasks.get(key)
        prev_status = prev.status if prev else None

        started = (prev.startedAt if prev else None) or now
        finished = prev.finishedAt if prev else None
        st = status.upper()
        if st in ("FINISHED", "ERROR", "FAILED"):
            finished = finished or now
        elif prev and prev.finishedAt:
            # reopened / follow-up: clear finished if running again
            if st in ("RUNNING", "CREATING", "WORKING", "IN_PROGRESS"):
                finished = None

        rec = TaskRecord(
            sessionId=session_id,
            taskId=task_id,
            title=title or (prev.title if prev else "") or "(untitled)",
            status=st,
            startedAt=started,
            finishedAt=finished,
            lastMessage=last_message or (prev.lastMessage if prev else "") or "",
            updatedAt=now,
        )
        tasks[key] = rec

        notified: Dict[str, str] = dict(data.get("notifiedTerminal") or {})
        # Allow a new terminal notification if the same task is resumed after completion.
        if st in ("RUNNING", "CREATING", "WORKING", "IN_PROGRESS") and prev_status in (
            "FINISHED",
            "ERROR",
            "FAILED",
        ):
            prefix = f"{key}::"
            notified = {k: v for k, v in notified.items() if not k.startswith(prefix)}

        should_notify = False
        if st in ("FINISHED", "ERROR", "FAILED"):
            terminal_key = f"{key}::{st}"
            if notified.get(terminal_key) != "1":
                should_notify = True
                notified[terminal_key] = "1"

        data["tasks"] = [asdict(t) for t in tasks.values()]
        data["notifiedTerminal"] = notified
        data["version"] = 1
        save_state_raw(state_path, data)
        return rec, should_notify, prev_status
    finally:
        _release_lock(fd, lock_path)


def clear_finished(state_path: str) -> None:
    lock_path = default_lock_path(state_path)
    fd = _acquire_lock(lock_path)
    try:
        data = load_state_raw(state_path)
        keep = []
        for row in data.get("tasks") or []:
            st = str(row.get("status") or "").upper()
            if st not in ("FINISHED", "ERROR", "FAILED"):
                keep.append(row)
        data["tasks"] = keep
        save_state_raw(state_path, data)
    finally:
        _release_lock(fd, lock_path)
