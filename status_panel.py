"""
Tkinter status panel: polls state.json and shows all Cursor task rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

# Ensure imports work when run as script from this directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from state_store import clear_finished, default_state_path, load_state_raw, tasks_from_state


def _read_state(path: str):
    try:
        data = load_state_raw(path)
        return tasks_from_state(data)
    except (OSError, json.JSONDecodeError):
        return []


class StatusPanelApp:
    def __init__(self, state_path: str, poll_ms: int = 500) -> None:
        self.state_path = state_path
        self.poll_ms = poll_ms
        self.root = tk.Tk()
        self.root.title("Cursor 任务状态")
        self.root.geometry("920x420")
        self.root.minsize(640, 280)

        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)

        ttk.Label(top, text=f"状态文件: {state_path}", font=("Segoe UI", 9)).pack(side=tk.LEFT)

        ttk.Button(top, text="刷新", command=self.refresh_now).pack(side=tk.RIGHT, padx=4)
        ttk.Button(top, text="清空已完成", command=self.on_clear_finished).pack(side=tk.RIGHT)

        body = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        body.pack(fill=tk.BOTH, expand=True)

        cols = ("workspace", "sessionId", "taskId", "title", "status", "updatedAt", "lastMessage")
        self.tree = ttk.Treeview(body, columns=cols, show="headings", height=14)
        headings = {
            "workspace": "工作区",
            "sessionId": "会话(conversation)",
            "taskId": "任务ID",
            "title": "标题",
            "status": "状态",
            "updatedAt": "更新时间",
            "lastMessage": "最后消息",
        }
        widths = {
            "workspace": 100,
            "sessionId": 120,
            "taskId": 100,
            "title": 180,
            "status": 80,
            "updatedAt": 150,
            "lastMessage": 220,
        }
        for c in cols:
            self.tree.heading(c, text=headings[c])
            self.tree.column(c, width=widths[c], stretch=True)

        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("error", background="#ffdddd")
        self.tree.tag_configure("running", background="#fff8dc")
        self.tree.tag_configure("done", background="#e8f5e9")

        self._rows_by_key: dict[str, str] = {}
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        self.refresh_now()
        self.root.after(self.poll_ms, self._tick)

    def _tick(self) -> None:
        self.refresh_now()
        self.root.after(self.poll_ms, self._tick)

    def refresh_now(self) -> None:
        tasks = _read_state(self.state_path)
        active = {"RUNNING", "CREATING", "WORKING", "IN_PROGRESS"}

        def is_active(t) -> bool:
            return t.status.upper() in active

        running = [t for t in tasks if is_active(t)]
        other = [t for t in tasks if not is_active(t)]
        running.sort(key=lambda t: t.updatedAt or "", reverse=True)
        other.sort(key=lambda t: t.updatedAt or "", reverse=True)
        tasks_sorted = running + other
        wanted = {t.key() for t in tasks_sorted}

        for key, iid in list(self._rows_by_key.items()):
            if key not in wanted:
                self.tree.delete(iid)
                del self._rows_by_key[key]

        for t in tasks_sorted:
            key = t.key()
            ws = (t.workspace or "")[:20]
            vals = (
                ws,
                t.sessionId[:14] + ("…" if len(t.sessionId) > 14 else ""),
                t.taskId[:16] + ("…" if len(t.taskId) > 16 else ""),
                t.title[:80],
                t.status,
                t.updatedAt,
                (t.lastMessage or "")[:120],
            )
            tag = self._row_tag(t.status)
            if key in self._rows_by_key:
                iid = self._rows_by_key[key]
                self.tree.item(iid, values=vals, tags=(tag,))
            else:
                iid = self.tree.insert("", tk.END, values=vals, tags=(tag,))
                self._rows_by_key[key] = iid

    @staticmethod
    def _row_tag(status: str) -> str:
        s = status.upper()
        if s in ("ERROR", "FAILED"):
            return "error"
        if s in ("RUNNING", "CREATING", "WORKING", "IN_PROGRESS"):
            return "running"
        if s in ("FINISHED",):
            return "done"
        return ""

    def on_clear_finished(self) -> None:
        if not messagebox.askyesno("确认", "清除所有已完成/失败的任务记录？"):
            return
        try:
            clear_finished(self.state_path)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("错误", str(e))
            return
        self.refresh_now()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ap = argparse.ArgumentParser(description="Cursor task status panel")
    ap.add_argument("--state", default=default_state_path(), help="Path to state.json")
    ap.add_argument("--poll", type=int, default=500, help="Poll interval ms")
    args = ap.parse_args()
    path = os.path.expandvars(os.path.expanduser(args.state))
    app = StatusPanelApp(path, poll_ms=max(200, args.poll))
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
