"""Shared extension contracts for history and desktop notification delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from homelab_monitor.models import Severity


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware time."""


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    event_key: str
    title: str
    body: str
    severity: Severity
    icon_name: str = "server-database"


class NotificationSink(Protocol):
    def send(self, message: NotificationMessage) -> None:
        """Deliver one desktop notification or raise on failure."""
