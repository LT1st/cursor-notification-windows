"""
CLI + Cursor hook stdin: merge task state and optionally toast on terminal states.

Hook mode: `python report_task.py --hook` reads JSON from stdin (Cursor command hook).
Manual mode: explicit --session/--task/--status/...
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, Optional, Tuple

from notifier import show_toast
from state_store import default_state_path, merge_task_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cursor_notification] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _extract_from_hook(payload: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """
    Best-effort mapping of Cursor hook JSON to our fields.
    Shape may vary by Cursor version; we try several common paths.
    """
    session = (
        str(
            payload.get("sessionId")
            or payload.get("session_id")
            or payload.get("conversationId")
            or payload.get("conversation_id")
            or payload.get("id")
            or ""
        ).strip()
    )
    task = str(
        payload.get("taskId")
        or payload.get("task_id")
        or payload.get("requestId")
        or payload.get("request_id")
        or payload.get("runId")
        or payload.get("run_id")
        or ""
    ).strip()
    title = str(
        payload.get("title")
        or payload.get("name")
        or payload.get("summary")
        or "Agent task"
    ).strip()
    status = str(
        payload.get("status")
        or payload.get("state")
        or "FINISHED"
    ).strip()
    last_message = str(
        payload.get("lastMessage")
        or payload.get("message")
        or payload.get("result")
        or ""
    ).strip()

    # Nested common patterns
    if not session and isinstance(payload.get("session"), dict):
        session = str(payload["session"].get("id") or "").strip()
    if not task and isinstance(payload.get("agent"), dict):
        task = str(payload["agent"].get("id") or "").strip()

    if not session:
        session = "default-session"
    if not task:
        task = str(uuid.uuid4())

    st = status.upper()
    if st in ("DONE", "COMPLETE", "COMPLETED", "SUCCESS"):
        st = "FINISHED"
    if st in ("FAIL", "FAILURE"):
        st = "ERROR"

    return session, task, title, st, last_message


def _run_hook(state_path: str) -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            log.warning("Hook stdin empty; nothing to record")
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            log.warning("Hook stdin is not a JSON object")
            return 0
        session, task, title, status, last_message = _extract_from_hook(payload)
    except json.JSONDecodeError as e:
        log.error("Invalid hook JSON: %s", e)
        return 0

    return _apply_and_notify(state_path, session, task, title, status, last_message)


def _apply_and_notify(
    state_path: str,
    session_id: str,
    task_id: str,
    title: str,
    status: str,
    last_message: str,
) -> int:
    rec, should_notify, _prev = merge_task_update(
        state_path,
        session_id=session_id,
        task_id=task_id,
        title=title,
        status=status,
        last_message=last_message,
    )
    if should_notify and rec.status in ("FINISHED", "ERROR", "FAILED"):
        label = "完成" if rec.status == "FINISHED" else "结束/失败"
        show_toast(
            f"Cursor 任务{label}",
            f"{rec.title}\n会话: {rec.sessionId[:8]}…",
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cursor task reporter for notification panel")
    ap.add_argument("--hook", action="store_true", help="Read Cursor hook JSON from stdin")
    ap.add_argument("--state", default=default_state_path(), help="Path to state.json")
    ap.add_argument("--session", default="", help="Session id (manual mode)")
    ap.add_argument("--task", default="", help="Task id (manual mode)")
    ap.add_argument("--title", default="Manual task", help="Task title (manual mode)")
    ap.add_argument("--status", default="FINISHED", help="RUNNING|FINISHED|ERROR|...")
    ap.add_argument("--message", default="", help="Last message snippet")
    args = ap.parse_args()

    state_path = os.path.expandvars(os.path.expanduser(args.state))
    if args.hook:
        return _run_hook(state_path)

    session = args.session or "manual-session"
    task = args.task or str(uuid.uuid4())
    return _apply_and_notify(state_path, session, task, args.title, args.status, args.message)


if __name__ == "__main__":
    raise SystemExit(main())
