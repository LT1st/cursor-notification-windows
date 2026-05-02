"""Windows toast notifications with fallbacks."""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


def show_toast(title: str, body: str, app_id: str = "Cursor.TaskNotify") -> None:
    """
    Show a non-blocking Windows notification.
    Tries win11toast first, then plyer.
    """
    title = (title or "Cursor")[:128]
    body = (body or "")[:512]

    errors: list[str] = []

    # win11toast (often async API; may require newer Python)
    try:
        from win11toast import toast as win11_toast  # type: ignore

        import inspect

        if inspect.iscoroutinefunction(win11_toast):
            import asyncio

            asyncio.run(win11_toast(title, body, app_id=app_id))
        else:
            win11_toast(title, body, app_id=app_id)
        return
    except BaseException as e:  # noqa: BLE001
        errors.append(f"win11toast: {e}")

    try:
        from plyer import notification  # type: ignore

        notification.notify(title=title, message=body, app_name="Cursor", timeout=8)
        return
    except Exception as e:  # noqa: BLE001
        errors.append(f"plyer: {e}")

    msg = "; ".join(errors)
    logger.warning("Toast unavailable (%s)", msg)
    print(f"[cursor_notification] {title}: {body}", file=sys.stderr)
