"""Windows toast notifications for the daily incubation cycle (scripts/run_incubation_cycle.py).
Best-effort only: a notification failure (no display session, winotify not installed, etc.)
must never fail the scheduled task itself — the cycle's real output is the registry/log/
dashboard, this is just a convenience alert on top of it.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

APP_ID = "NZ Quant Trader"


def send_toast(title: str, message: str) -> None:
    try:
        from winotify import Notification
    except ImportError:
        logger.info("winotify not installed — skipping toast notification")
        return

    try:
        Notification(app_id=APP_ID, title=title, msg=message).show()
    except Exception as exc:  # pragma: no cover - depends on live Windows notification service
        logger.warning("Failed to show toast notification: %s", exc)
