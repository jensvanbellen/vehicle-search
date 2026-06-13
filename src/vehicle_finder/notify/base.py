"""Notifier interface. Default is a no-op — nothing is sent unless explicitly configured."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from vehicle_finder.logging import get_logger

log = get_logger("notify")


@dataclass
class Notification:
    title: str
    body: str  # markdown


class Notifier(Protocol):
    def send(self, notification: Notification) -> None: ...


class NullNotifier:
    """Sends nothing (the safe default). Logs that it would have sent."""

    def send(self, notification: Notification) -> None:
        log.info("notification_suppressed", title=notification.title)


class ConsoleNotifier:
    """Prints the digest to stdout — local only, never leaves the machine."""

    def send(self, notification: Notification) -> None:
        print(f"\n=== {notification.title} ===\n{notification.body}")


def get_notifier() -> Notifier:
    """Return the configured notifier. Until real channels are wired, this is the no-op."""
    from vehicle_finder.config import get_settings

    return ConsoleNotifier() if get_settings().notify_enabled else NullNotifier()
