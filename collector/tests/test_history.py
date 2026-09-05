from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic, sleep

import pytest
from homelab_monitor import history
from homelab_monitor.events import IncidentEngine, TransitionPolicy
from homelab_monitor.history import (
    HistoryCoordinator,
    HistoryLimits,
    HistoryMigrationError,
    HistoryStore,
    Observation,
)
from homelab_monitor.models import Status

NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)


def _observation(
    resource_id: str,
    status: Status,
    *,
    at: datetime = NOW,
    value: float | None = None,
) -> Observation:
    return Observation(
        resource_id=resource_id,
        resource_name=resource_id.title(),
        status=status,
        observed_at=at,
        metric="latency",
        value=value,
        unit="ms",
    )


def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


def test_migration_is_versioned_and_history_survives_restart(tmp_path) -> None:
    path = tmp_path / "state" / "history.sqlite3"
    store = HistoryStore(path)
    assert store.schema_version() == 1
    store.record_observation(_observation("nas", Status.HEALTHY, value=4))
    store.close()

    reopened = HistoryStore(path)
    model = reopened.read_model()
    reopened.close()

    assert model.trends[0].resource_id == "nas"
    assert model.trends[0].points[0].value == 4


def test_history_limits_are_constructed_from_validated_config() -> None:
    limits = HistoryLimits.from_config(
        {
            "retention_days": 7,
            "max_observations_per_resource": 10,
            "max_total_observations": 20,
            "recent_event_limit": 5,
            "trend_point_limit": 3,
        }
    )

    assert limits.retention_days == 7
    assert limits.max_events_per_resource == 10
    assert limits.max_events == 20


def test_failed_migration_rolls_back_all_schema_changes(tmp_path, monkeypatch) -> None:
    migrations = history._MIGRATIONS + ((2, ("THIS IS NOT SQL",)),)
    monkeypatch.setattr(history, "_MIGRATIONS", migrations)
    path = tmp_path / "history.sqlite3"

    with pytest.raises(HistoryMigrationError, match="migration failed"):
        HistoryStore(path)

    connection = sqlite3.connect(path)
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    connection.close()
    assert tables == []


def test_newer_schema_fails_without_discarding_history(tmp_path) -> None:
    path = tmp_path / "history.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    connection.execute("INSERT INTO schema_migrations VALUES (99, 'future')")
    connection.commit()
    connection.close()

    with pytest.raises(HistoryMigrationError, match="newer than supported"):
        HistoryStore(path)

    connection = sqlite3.connect(path)
    assert connection.execute("SELECT version FROM schema_migrations").fetchone()[0] == 99
    connection.close()


def test_retention_enforces_age_per_resource_global_and_event_caps(tmp_path) -> None:
    limits = HistoryLimits(
        retention_days=2,
        max_observations_per_resource=2,
        max_total_observations=3,
        max_events_per_resource=2,
        max_events=2,
        recent_event_limit=10,
        trend_point_limit=10,
    )
    store = HistoryStore(tmp_path / "history.sqlite3", limits=limits)
    engine = IncidentEngine(
        store,
        policy=TransitionPolicy(notifications_enabled=False),
    )
    store.record_observation(_observation("old", Status.HEALTHY, at=NOW - timedelta(days=3)))
    for offset in range(3):
        store.record_observation(
            _observation("nas", Status.HEALTHY, at=NOW + timedelta(minutes=offset))
        )
    store.record_observation(_observation("router", Status.HEALTHY, at=NOW))
    store.record_observation(_observation("ups", Status.HEALTHY, at=NOW))
    engine.process(_observation("events", Status.DEGRADED, at=NOW))
    engine.process(_observation("events", Status.UNAVAILABLE, at=NOW + timedelta(minutes=1)))
    engine.process(_observation("events", Status.HEALTHY, at=NOW + timedelta(minutes=2)))

    store.prune(NOW + timedelta(hours=1))
    counts = store.counts()
    model = store.read_model()
    store.close()

    assert counts["observations"] == 3
    assert counts["events"] == 2
    assert len(model.recent_events) == 2


def test_coordinator_queue_is_bounded_and_refreshes_cached_model(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    entered = Event()
    release = Event()

    def blocked_handler(observation: Observation) -> None:
        entered.set()
        release.wait(1)
        store.record_observation(observation)

    coordinator = HistoryCoordinator(store, handler=blocked_handler, queue_size=1)
    coordinator.start()
    assert coordinator.submit(_observation("first", Status.HEALTHY))
    assert entered.wait(0.5)
    assert coordinator.submit(_observation("second", Status.HEALTHY))
    started = monotonic()
    assert not coordinator.submit(_observation("third", Status.HEALTHY))
    assert monotonic() - started < 0.05

    release.set()
    _wait_for(lambda: coordinator.statistics().processed == 2)
    coordinator.stop()
    snapshot = coordinator.cache.snapshot()
    statistics = coordinator.statistics()
    store.close()

    assert statistics.dropped == 1
    assert {trend.resource_id for trend in snapshot.trends} == {"first", "second"}


def test_cached_snapshots_are_independent_copies(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    coordinator = HistoryCoordinator(store)
    coordinator.start()
    assert coordinator.submit(_observation("nas", Status.HEALTHY, value=5))
    _wait_for(lambda: coordinator.statistics().processed == 1)
    first = coordinator.cache.snapshot()
    first.trends[0].points.clear()
    second = coordinator.cache.snapshot()
    coordinator.stop()
    store.close()

    assert len(second.trends[0].points) == 1
