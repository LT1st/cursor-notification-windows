"""
CLI + Cursor hook stdin: merge task state and optionally toast on terminal states.

Hook mode: `python report_task.py --hook` reads JSON from stdin (Cursor command hook).
Uses Cursor common hook fields: conversation_id, workspace_roots, hook_event_name, etc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, Tuple

from notifier import show_toast
from state_store import default_state_path, merge_task_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cursor_notification] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def _workspace_label(payload: Dict[str, Any]) -> str:
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots") or []
    if isinstance(roots, list) and roots:
        try:
            return os.path.basename(str(roots[0]).rstrip("/\\"))[:80]
        except (TypeError, ValueError):
            return ""
    return ""


def _conversation_id(payload: Dict[str, Any]) -> str:
    return str(
        payload.get("conversation_id")
        or payload.get("conversationId")
        or ""
    ).strip()


def _derive_session_id(payload: Dict[str, Any]) -> str:
    """One row per composer = stable conversation_id (Cursor docs)."""
    cid = _conversation_id(payload)
    if cid:
        return cid
    sid = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    if sid:
        return sid
    roots = payload.get("workspace_roots") or payload.get("workspaceRoots") or []
    if isinstance(roots, list) and roots:
        h = hashlib.sha256(str(roots[0]).encode("utf-8")).hexdigest()[:16]
        return f"no-conversation-{h}"
    return "default-session"


def _normalize_agent_status(raw: str) -> str:
    m = (raw or "").strip().lower()
    if m in ("completed", "done", "complete", "success"):
        return "FINISHED"
    if m in ("error", "failed", "failure"):
        return "ERROR"
    if m in ("aborted", "abort"):
        return "FINISHED"
    u = raw.strip().upper()
    if u in ("DONE", "COMPLETE", "COMPLETED", "SUCCESS"):
        return "FINISHED"
    if u in ("FAIL", "FAILURE"):
        return "ERROR"
    return u


def _hook_event(payload: Dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or payload.get("hookEventName") or "").strip().lower()


def _extract_from_hook(payload: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    """
    Map Cursor hook JSON -> (session_id, task_id, title, status, last_message, workspace_label).

    Main composer: fixed task_id ``composer`` so sessionStart + stop update the same row
    across turns; each *conversation* (window/tab) has its own conversation_id.
    """
    workspace = _workspace_label(payload)
    event = _hook_event(payload)

    # --- Subagent lifecycle (separate row per subagent_id)
    if event == "subagentstop" or (
        payload.get("subagent_type") is not None
        and payload.get("summary") is not None
    ):
        parent = str(
            payload.get("parent_conversation_id")
            or payload.get("parentConversationId")
            or _conversation_id(payload)
            or _derive_session_id(payload)
        ).strip()
        sid = str(payload.get("subagent_id") or payload.get("subagentId") or "").strip()
        if not sid:
            sid = str(payload.get("tool_call_id") or payload.get("toolCallId") or uuid.uuid4())
        task_id = f"subagent:{sid}"
        session = parent or _derive_session_id(payload)
        raw_st = str(payload.get("status") or "completed").strip()
        st = _normalize_agent_status(raw_st)
        title = (
            str(payload.get("description") or payload.get("task") or "Subagent")[:120]
        ).strip() or "Subagent"
        if workspace:
            title = f"{title} · {workspace}"
        last = str(payload.get("summary") or "")[:800]
        return session, task_id, title, st, last, workspace

    if event == "subagentstart":
        parent = str(
            payload.get("parent_conversation_id")
            or payload.get("parentConversationId")
            or _conversation_id(payload)
            or _derive_session_id(payload)
        ).strip()
        sid = str(payload.get("subagent_id") or payload.get("subagentId") or "").strip()
        if not sid:
            sid = str(payload.get("tool_call_id") or payload.get("toolCallId") or uuid.uuid4())
        task_id = f"subagent:{sid}"
        session = parent or _derive_session_id(payload)
        typ = str(payload.get("subagent_type") or payload.get("subagentType") or "subagent")
        title = str(payload.get("task") or payload.get("description") or typ)[:120] or typ
        if workspace:
            title = f"{title} · {workspace}"
        return session, task_id, title, "RUNNING", "", workspace

    # --- Session lifecycle (main composer row)
    if event == "sessionstart":
        session = _derive_session_id(payload)
        task_id = "composer"
        mode = str(payload.get("composer_mode") or payload.get("composerMode") or "agent")
        title = (mode + (f" · {workspace}" if workspace else ""))[:120] or "Composer"
        return session, task_id, title, "RUNNING", "", workspace

    if event == "sessionend":
        session = str(
            payload.get("session_id")
            or payload.get("sessionId")
            or _conversation_id(payload)
            or _derive_session_id(payload)
        ).strip()
        task_id = "composer"
        reason = str(payload.get("reason") or "completed").strip().lower()
        if reason == "error":
            st = "ERROR"
        else:
            st = "FINISHED"
        title = f"会话结束 ({reason})" + (f" · {workspace}" if workspace else "")
        msg = str(payload.get("error_message") or payload.get("final_status") or "")[:500]
        return session, task_id, title, st, msg, workspace

    # --- Main agent stop (composer loop ends)
    if event == "stop" or (
        not event
        and str(payload.get("status", "")).lower() in ("completed", "aborted", "error")
        and payload.get("subagent_type") is None
        and payload.get("subagentType") is None
    ):
        session = _derive_session_id(payload)
        task_id = "composer"
        raw_st = str(payload.get("status") or "completed").strip()
        st = _normalize_agent_status(raw_st)
        title = str(payload.get("title") or payload.get("name") or "Agent 任务")[:120]
        if not title or title == "Agent task":
            title = "Agent 任务"
        if workspace:
            title = f"{title} · {workspace}"
        last = str(
            payload.get("lastMessage")
            or payload.get("message")
            or payload.get("result")
            or ""
        )[:800]
        return session, task_id, title, st, last, workspace

    # --- Legacy / unknown shape: avoid collapsing unrelated windows via bare ``id``
    session = (
        str(
            payload.get("conversation_id")
            or payload.get("conversationId")
            or payload.get("session_id")
            or payload.get("sessionId")
            or ""
        ).strip()
    )
    if not session:
        session = _derive_session_id(payload)
    task = str(
        payload.get("generation_id")
        or payload.get("generationId")
        or payload.get("taskId")
        or payload.get("task_id")
        or ""
    ).strip()
    if not task:
        task = str(uuid.uuid4())
    title = str(payload.get("title") or payload.get("name") or payload.get("summary") or "Agent task")[:120]
    status = str(payload.get("status") or payload.get("state") or "FINISHED").strip()
    last_message = str(payload.get("lastMessage") or payload.get("message") or "")[:800]
    st = _normalize_agent_status(status)
    if workspace and title and workspace not in title:
        title = f"{title} · {workspace}"[:120]
    return session, task, title, st, last_message, workspace


def _run_hook(state_path: str) -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            log.warning("Hook stdin empty; nothing to record")
            print("{}", flush=True)
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            log.warning("Hook stdin is not a JSON object")
            print("{}", flush=True)
            return 0

        if os.environ.get("CURSOR_NOTIFICATION_DEBUG"):
            dbg = os.path.join(os.path.dirname(state_path) or ".", "last_hook.json")
            try:
                with open(dbg, "w", encoding="utf-8") as df:
                    json.dump(payload, df, ensure_ascii=False, indent=2)
            except OSError as e:
                log.debug("debug write failed: %s", e)

        session, task, title, status, last_message, workspace = _extract_from_hook(payload)
        log.info(
            "hook event=%s session=%s task=%s status=%s ws=%s",
            payload.get("hook_event_name"),
            session[:12] + "…" if len(session) > 12 else session,
            task,
            status,
            workspace or "-",
        )
        code = _apply_and_notify(
            state_path, session, task, title, status, last_message, workspace
        )
        # stop / subagentStop: empty object = no auto follow-up (Cursor hook contract)
        print("{}", flush=True)
        return code
    except json.JSONDecodeError as e:
        log.error("Invalid hook JSON: %s", e)
        print("{}", flush=True)
        return 0


def _apply_and_notify(
    state_path: str,
    session_id: str,
    task_id: str,
    title: str,
    status: str,
    last_message: str,
    workspace: str = "",
) -> int:
    rec, should_notify, _prev = merge_task_update(
        state_path,
        session_id=session_id,
        task_id=task_id,
        title=title,
        status=status,
        last_message=last_message,
        workspace=workspace,
    )
    if should_notify and rec.status in ("FINISHED", "ERROR", "FAILED"):
        label = "完成" if rec.status == "FINISHED" else "结束/失败"
        tail = rec.workspace or (rec.sessionId[:8] + "…" if len(rec.sessionId) > 8 else rec.sessionId)
        show_toast(
            f"Cursor 任务{label}",
            f"{rec.title}\n工作区/会话: {tail}",
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cursor task reporter for notification panel")
    ap.add_argument("--hook", action="store_true", help="Read Cursor hook JSON from stdin")
    ap.add_argument("--state", default=default_state_path(), help="Path to state.json")
    ap.add_argument("--workspace", default="", help="Workspace label (manual mode)")
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
    return _apply_and_notify(
        state_path,
        session,
        task,
        args.title,
        args.status,
        args.message,
        workspace=args.workspace,
    )


if __name__ == "__main__":
    raise SystemExit(main())
