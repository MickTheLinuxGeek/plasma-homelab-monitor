from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from threading import Event
from time import monotonic, sleep

from homelab_monitor.contracts import NotificationMessage
from homelab_monitor.events import IncidentEngine, TransitionPolicy
from homelab_monitor.history import HistoryStore, Observation
from homelab_monitor.models import Severity, Status
from homelab_monitor.notifications import (
    JeepneyNotificationSink,
    NotificationDispatcher,
    QuietHours,
)
from jeepney.low_level import HeaderFields

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


@dataclass
class MutableClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class CaptureSink:
    def __init__(self) -> None:
        self.messages: list[NotificationMessage] = []

    def send(self, message: NotificationMessage) -> None:
        self.messages.append(message)


def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def _create_failure(
    store: HistoryStore,
    clock: MutableClock,
    resource_id: str = "nas",
) -> int:
    engine = IncidentEngine(
        store,
        clock=clock,
        policy=TransitionPolicy(
            notifications_enabled=True,
            degraded_grace=timedelta(0),
            unavailable_grace=timedelta(0),
        ),
    )
    result = engine.process(
        Observation(resource_id, resource_id.title(), Status.DEGRADED, clock.current)
    )
    assert result.incident_id is not None
    return result.incident_id


def test_quiet_hours_handle_same_day_and_midnight_windows() -> None:
    daytime = QuietHours(enabled=True, start=time(9), end=time(17), timezone="UTC")
    overnight = QuietHours(enabled=True, start=time(22), end=time(7), timezone="UTC")

    assert daytime.is_quiet(datetime(2026, 9, 5, 12, tzinfo=UTC))
    assert not daytime.is_quiet(datetime(2026, 9, 5, 18, tzinfo=UTC))
    assert overnight.is_quiet(datetime(2026, 9, 5, 23, tzinfo=UTC))
    assert overnight.is_quiet(datetime(2026, 9, 6, 6, 59, tzinfo=UTC))
    assert not overnight.is_quiet(datetime(2026, 9, 6, 7, tzinfo=UTC))


def test_dispatcher_retains_pending_during_quiet_hours(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(datetime(2026, 9, 5, 23, tzinfo=UTC))
    incident_id = _create_failure(store, clock)
    sink = CaptureSink()
    dispatcher = NotificationDispatcher(
        store,
        sink,
        clock=clock,
        quiet_hours=QuietHours(enabled=True, start=time(22), end=time(7), timezone="UTC"),
    )
    dispatcher.start()

    assert dispatcher.dispatch_due() == 0
    assert store.notification_state(f"incident:{incident_id}:failure") == "pending"
    clock.current = datetime(2026, 9, 6, 7, tzinfo=UTC)
    assert dispatcher.dispatch_due() == 1
    _wait_for(lambda: len(sink.messages) == 1)
    dispatcher.stop()
    store.close()


def test_failure_recovery_during_quiet_hours_is_never_delivered(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(datetime(2026, 9, 5, 23, tzinfo=UTC))
    incident_id = _create_failure(store, clock)
    engine = IncidentEngine(
        store,
        clock=clock,
        policy=TransitionPolicy(notifications_enabled=True),
    )
    dispatcher = NotificationDispatcher(
        store,
        CaptureSink(),
        clock=clock,
        quiet_hours=QuietHours(enabled=True, start=time(22), end=time(7), timezone="UTC"),
    )
    assert dispatcher.dispatch_due() == 0

    clock.current += timedelta(minutes=5)
    engine.process(Observation("nas", "Nas", Status.HEALTHY, clock.current))
    clock.current = datetime(2026, 9, 6, 7, tzinfo=UTC)

    assert dispatcher.dispatch_due() == 0
    assert store.notification_state(f"incident:{incident_id}:failure") == "cancelled"
    store.close()


def test_slow_sink_is_isolated_behind_bounded_queue(tmp_path) -> None:
    class SlowSink:
        def __init__(self) -> None:
            self.entered = Event()
            self.release = Event()

        def send(self, message: NotificationMessage) -> None:
            self.entered.set()
            self.release.wait(1)

    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    _create_failure(store, clock, "one")
    _create_failure(store, clock, "two")
    _create_failure(store, clock, "three")
    sink = SlowSink()
    dispatcher = NotificationDispatcher(store, sink, clock=clock, queue_size=1)
    dispatcher.start()
    first = store.pending_notifications(NOW)[0]
    assert dispatcher.submit(first)
    assert sink.entered.wait(0.5)
    pending = store.pending_notifications(NOW)
    second = next(item for item in pending if item.id != first.id)
    assert dispatcher.submit(second)
    third = next(item for item in pending if item.id not in {first.id, second.id})
    started = monotonic()
    assert not dispatcher.submit(third)
    assert monotonic() - started < 0.05

    sink.release.set()
    _wait_for(lambda: dispatcher.statistics().delivered == 2)
    dispatcher.stop()
    statistics = dispatcher.statistics()
    store.close()
    assert statistics.dropped == 1


def test_delivery_failures_retry_then_cancel_without_stopping_worker(tmp_path) -> None:
    class FailingSink:
        def send(self, message: NotificationMessage) -> None:
            raise RuntimeError("session bus unavailable")

    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    incident_id = _create_failure(store, clock)
    dispatcher = NotificationDispatcher(
        store,
        FailingSink(),
        clock=clock,
        retry_limit=2,
        retry_delay=timedelta(0),
    )
    dispatcher.start()
    assert dispatcher.dispatch_due() == 1
    _wait_for(lambda: dispatcher.statistics().failed == 1)
    assert dispatcher.dispatch_due() == 1
    _wait_for(lambda: dispatcher.statistics().failed == 2)
    dispatcher.stop()

    assert store.notification_state(f"incident:{incident_id}:failure") == "cancelled"
    store.close()


def test_interrupted_send_is_cancelled_on_restart_to_prevent_duplicates(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    clock = MutableClock(NOW)
    store = HistoryStore(path)
    incident_id = _create_failure(store, clock)
    pending = store.pending_notifications(NOW)[0]
    assert store.claim_notification(pending.id, NOW)
    store.close()

    reopened = HistoryStore(path)
    key = f"incident:{incident_id}:failure"
    assert reopened.notification_state(key) == "cancelled"
    assert reopened.pending_notifications(NOW + timedelta(days=1)) == ()
    reopened.close()


def test_jeepney_sink_builds_freedesktop_notify_call() -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.calls = []
            self.closed = False

        def send_and_get_reply(self, message, *, timeout=None):
            self.calls.append((message, timeout))
            return (1,)

        def close(self) -> None:
            self.closed = True

    connection = FakeConnection()
    sink = JeepneyNotificationSink(
        connection_factory=lambda: connection,
        timeout=1.5,
    )
    sink.send(
        NotificationMessage(
            event_key="incident:1:failure",
            title="NAS unavailable",
            body="The NAS stopped responding.",
            severity=Severity.CRITICAL,
            icon_name="network-server",
        )
    )
    sink.close()

    message, timeout = connection.calls[0]
    assert message.header.fields[HeaderFields.destination] == "org.freedesktop.Notifications"
    assert message.header.fields[HeaderFields.interface] == "org.freedesktop.Notifications"
    assert message.header.fields[HeaderFields.path] == "/org/freedesktop/Notifications"
    assert message.header.fields[HeaderFields.member] == "Notify"
    assert message.body[0:5] == (
        "Home-lab Monitor",
        0,
        "network-server",
        "NAS unavailable",
        "The NAS stopped responding.",
    )
    assert message.body[6]["urgency"] == ("y", 2)
    assert timeout == 1.5
    assert connection.closed
