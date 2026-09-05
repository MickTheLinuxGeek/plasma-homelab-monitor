"""Durable, isolated desktop notification delivery."""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from threading import Event, Lock, Thread
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

from homelab_monitor.contracts import Clock, NotificationMessage, NotificationSink
from homelab_monitor.history import HistoryStore, PendingNotification, UtcClock
from homelab_monitor.models import Severity

logger = logging.getLogger(__name__)


class DBusConnection(Protocol):
    def send_and_get_reply(self, message: Any, *, timeout: float | None = None) -> Any:
        """Send a method call and wait for its reply."""

    def close(self) -> None:
        """Close the connection."""


class JeepneyNotificationSink:
    """Send messages through org.freedesktop.Notifications on the session bus."""

    _address = DBusAddress(
        "/org/freedesktop/Notifications",
        bus_name="org.freedesktop.Notifications",
        interface="org.freedesktop.Notifications",
    )

    def __init__(
        self,
        *,
        app_name: str = "Home-lab Monitor",
        timeout: float = 3.0,
        connection_factory: Callable[[], DBusConnection] | None = None,
    ) -> None:
        self.app_name = app_name
        self.timeout = timeout
        self._connection_factory = connection_factory or open_dbus_connection
        self._connection: DBusConnection | None = None
        self._lock = Lock()

    def send(self, message: NotificationMessage) -> None:
        urgency = {
            Severity.INFO: 0,
            Severity.WARNING: 1,
            Severity.CRITICAL: 2,
        }[message.severity]
        call = new_method_call(
            self._address,
            "Notify",
            "susssasa{sv}i",
            (
                self.app_name,
                0,
                message.icon_name,
                message.title,
                message.body,
                [],
                {
                    "urgency": ("y", urgency),
                    "desktop-entry": ("s", "homelab-monitor"),
                    "category": ("s", "device"),
                },
                -1,
            ),
        )
        with self._lock:
            if self._connection is None:
                self._connection = self._connection_factory()
            self._connection.send_and_get_reply(call, timeout=self.timeout)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None


@dataclass(frozen=True, slots=True)
class QuietHours:
    enabled: bool = False
    start: time = time(22, 0)
    end: time = time(7, 0)
    timezone: str = "local"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> QuietHours:
        return cls(
            enabled=bool(config.get("enabled", False)),
            start=time.fromisoformat(str(config.get("start", "22:00"))),
            end=time.fromisoformat(str(config.get("end", "07:00"))),
            timezone=str(config.get("timezone", "local")),
        )

    def is_quiet(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        zone = now.astimezone().tzinfo if self.timezone == "local" else ZoneInfo(self.timezone)
        local_time = now.astimezone(zone).time().replace(tzinfo=None)
        if self.start == self.end:
            return True
        if self.start < self.end:
            return self.start <= local_time < self.end
        return local_time >= self.start or local_time < self.end


@dataclass(frozen=True, slots=True)
class DispatcherStatistics:
    enqueued: int
    delivered: int
    dropped: int
    failed: int


class NotificationDispatcher:
    """Deliver claimed notifications on a dedicated bounded worker."""

    def __init__(
        self,
        store: HistoryStore,
        sink: NotificationSink,
        *,
        clock: Clock | None = None,
        quiet_hours: QuietHours | None = None,
        queue_size: int = 64,
        retry_limit: int = 3,
        retry_delay: timedelta = timedelta(seconds=5),
    ) -> None:
        if queue_size < 1 or retry_limit < 1 or retry_delay < timedelta(0):
            raise ValueError("dispatcher limits must be positive")
        self.store = store
        self.sink = sink
        self.clock = clock or UtcClock()
        self.quiet_hours = quiet_hours or QuietHours()
        self.retry_limit = retry_limit
        self.retry_delay = retry_delay
        self._queue: queue.Queue[PendingNotification] = queue.Queue(maxsize=queue_size)
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()
        self._enqueued_ids: set[int] = set()
        self._enqueued = 0
        self._delivered = 0
        self._dropped = 0
        self._failed = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="homelab-monitor-notifications",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    def dispatch_due(self, *, limit: int = 64) -> int:
        now = self.clock.now()
        if self.quiet_hours.is_quiet(now):
            return 0
        accepted = 0
        for delivery in self.store.pending_notifications(now, limit=limit):
            if self.submit(delivery):
                accepted += 1
            elif self._queue.full():
                break
        return accepted

    def submit(self, delivery: PendingNotification) -> bool:
        with self._lock:
            if delivery.id in self._enqueued_ids:
                return False
            try:
                self._queue.put_nowait(delivery)
            except queue.Full:
                self._dropped += 1
                return False
            self._enqueued_ids.add(delivery.id)
            self._enqueued += 1
            return True

    def statistics(self) -> DispatcherStatistics:
        with self._lock:
            return DispatcherStatistics(
                enqueued=self._enqueued,
                delivered=self._delivered,
                dropped=self._dropped,
                failed=self._failed,
            )

    def _run(self) -> None:
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                delivery = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                claimed_at = self.clock.now()
                if not self.store.claim_notification(delivery.id, claimed_at):
                    continue
                try:
                    self.sink.send(delivery.message)
                except Exception:
                    logger.exception("Notification delivery failed for %s", delivery.event_key)
                    self.store.mark_notification_failed(
                        delivery.id,
                        self.clock.now(),
                        retry_limit=self.retry_limit,
                        retry_delay=self.retry_delay,
                    )
                    with self._lock:
                        self._failed += 1
                else:
                    self.store.mark_notification_delivered(delivery.id, self.clock.now())
                    with self._lock:
                        self._delivered += 1
            finally:
                with self._lock:
                    self._enqueued_ids.discard(delivery.id)
                self._queue.task_done()
