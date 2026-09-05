from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from homelab_monitor.events import IncidentEngine, TransitionPolicy
from homelab_monitor.history import HistoryStore, Observation
from homelab_monitor.models import Severity, Status

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


@dataclass
class MutableClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


def _observation(status: Status, at: datetime, resource_id: str = "nas") -> Observation:
    return Observation(resource_id, resource_id.title(), status, at)


def _engine(store: HistoryStore, clock: MutableClock, **policy) -> IncidentEngine:
    settings = {
        "notifications_enabled": True,
        "degraded_grace": timedelta(seconds=60),
        "unavailable_grace": timedelta(seconds=90),
        "cooldown": timedelta(minutes=15),
    }
    settings.update(policy)
    return IncidentEngine(
        store,
        clock=clock,
        policy=TransitionPolicy(**settings),
    )


def test_transition_deduplication_and_grace_eligibility(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock)

    healthy = engine.process(_observation(Status.HEALTHY, NOW))
    failure = engine.process(_observation(Status.DEGRADED, NOW))
    duplicate = engine.process(_observation(Status.DEGRADED, NOW + timedelta(seconds=5)))

    assert healthy.event_id is None
    assert failure.event_id is not None
    assert failure.incident_id is not None
    assert duplicate.event_id is None
    assert store.pending_notifications(NOW + timedelta(seconds=59)) == ()
    due = store.pending_notifications(NOW + timedelta(seconds=60))
    assert len(due) == 1
    assert due[0].message.severity == Severity.WARNING
    assert len(store.read_model().recent_events) == 1
    store.close()


def test_unknown_status_transition_is_persisted_without_resolving_incident(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock)
    failure = engine.process(_observation(Status.DEGRADED, NOW))
    unknown = engine.process(_observation(Status.UNKNOWN, NOW + timedelta(minutes=1)))
    recovery = engine.process(_observation(Status.HEALTHY, NOW + timedelta(minutes=2)))

    events = store.read_model().recent_events
    assert unknown.event_id is not None
    assert recovery.incident_id == failure.incident_id
    assert [event.event_type for event in events] == ["recovery", "status", "failure"]
    store.close()


def test_dependent_event_can_be_correlated_to_a_parent(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock)
    parent = engine.process(_observation(Status.DEGRADED, NOW, "host"))
    child = engine.process(_observation(Status.DEGRADED, NOW, "container"))

    store.correlate_event(child.event_id, parent.event_id)
    events = {event.id: event for event in store.read_model().recent_events}
    store.close()

    assert events[child.event_id].parent_event_id == parent.event_id


def test_minimum_severity_filters_degraded_but_not_critical(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock, minimum_severity=Severity.CRITICAL)

    engine.process(_observation(Status.DEGRADED, NOW))
    assert store.pending_notifications(NOW + timedelta(minutes=2)) == ()
    engine.process(_observation(Status.UNAVAILABLE, NOW + timedelta(minutes=2)))

    due = store.pending_notifications(NOW + timedelta(minutes=4))
    store.close()
    assert len(due) == 1
    assert due[0].message.severity == Severity.CRITICAL


def test_recovery_cancels_undelivered_failure_and_sends_no_recovery(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock)
    failure = engine.process(_observation(Status.DEGRADED, NOW))
    key = f"incident:{failure.incident_id}:failure"

    clock.current = NOW + timedelta(seconds=30)
    recovery = engine.process(_observation(Status.HEALTHY, clock.current))

    assert recovery.recovered
    assert store.notification_state(key) == "cancelled"
    assert store.pending_notifications(NOW + timedelta(days=1)) == ()
    events = store.read_model().recent_events
    assert events[1].recovered_at is not None
    store.close()


def test_recovery_is_eligible_only_after_confirmed_failure_delivery(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock, degraded_grace=timedelta(0))
    failure = engine.process(_observation(Status.DEGRADED, NOW))
    pending = store.pending_notifications(NOW)[0]
    assert store.claim_notification(pending.id, NOW)
    assert store.mark_notification_delivered(pending.id, NOW)

    clock.current = NOW + timedelta(minutes=1)
    engine.process(_observation(Status.HEALTHY, clock.current))

    due = store.pending_notifications(clock.current)
    store.close()
    assert len(due) == 1
    assert due[0].event_key == f"incident:{failure.incident_id}:recovery"
    assert due[0].message.severity == Severity.INFO


def test_delivery_and_transition_state_survive_restart(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    clock = MutableClock(NOW)
    store = HistoryStore(path)
    engine = _engine(store, clock, degraded_grace=timedelta(0))
    failure = engine.process(_observation(Status.DEGRADED, NOW))
    pending = store.pending_notifications(NOW)[0]
    store.claim_notification(pending.id, NOW)
    store.mark_notification_delivered(pending.id, NOW)
    store.close()

    reopened = HistoryStore(path)
    restarted_engine = _engine(reopened, clock, degraded_grace=timedelta(0))
    duplicate = restarted_engine.process(_observation(Status.DEGRADED, NOW + timedelta(minutes=1)))
    key = f"incident:{failure.incident_id}:failure"

    assert duplicate.event_id is None
    assert reopened.notification_state(key) == "delivered"
    assert reopened.pending_notifications(NOW + timedelta(days=1)) == ()
    reopened.close()


def test_cooldown_delays_a_new_incident_for_same_resource(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    clock = MutableClock(NOW)
    engine = _engine(store, clock, degraded_grace=timedelta(0))
    first = engine.process(_observation(Status.DEGRADED, NOW))
    pending = store.pending_notifications(NOW)[0]
    store.claim_notification(pending.id, NOW)
    store.mark_notification_delivered(pending.id, NOW)
    clock.current = NOW + timedelta(minutes=1)
    engine.process(_observation(Status.HEALTHY, clock.current))
    recovery = store.pending_notifications(clock.current)[0]
    store.claim_notification(recovery.id, clock.current)
    store.mark_notification_delivered(recovery.id, clock.current)

    clock.current = NOW + timedelta(minutes=2)
    second = engine.process(_observation(Status.DEGRADED, clock.current))

    assert second.incident_id != first.incident_id
    assert store.pending_notifications(NOW + timedelta(minutes=14, seconds=59)) == ()
    due = store.pending_notifications(NOW + timedelta(minutes=15))
    store.close()
    assert len(due) == 1
    assert due[0].kind == "failure"
