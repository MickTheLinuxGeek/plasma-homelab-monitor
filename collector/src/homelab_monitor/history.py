"""SQLite-backed history, retention, and nonblocking observation coordination."""

from __future__ import annotations

import logging
import queue
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Protocol

from homelab_monitor.contracts import Clock, NotificationMessage
from homelab_monitor.models import (
    Severity,
    Status,
    TimelineEvent,
    TrendPoint,
    TrendSeries,
)

logger = logging.getLogger(__name__)


class HistoryMigrationError(RuntimeError):
    """Raised when the history schema cannot be safely migrated."""


class UtcClock:
    """Production clock implementation."""

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class HistoryLimits:
    retention_days: int = 30
    max_observations_per_resource: int = 1440
    max_total_observations: int = 50000
    max_events_per_resource: int = 1000
    max_events: int = 10000
    recent_event_limit: int = 20
    trend_point_limit: int = 30

    @classmethod
    def from_config(cls, config: dict[str, object]) -> HistoryLimits:
        return cls(
            retention_days=int(config.get("retention_days", 30)),
            max_observations_per_resource=int(config.get("max_observations_per_resource", 1440)),
            max_total_observations=int(config.get("max_total_observations", 50000)),
            max_events_per_resource=int(
                config.get(
                    "max_events_per_resource",
                    config.get("max_observations_per_resource", 1000),
                )
            ),
            max_events=int(config.get("max_events", config.get("max_total_observations", 10000))),
            recent_event_limit=int(config.get("recent_event_limit", 20)),
            trend_point_limit=int(config.get("trend_point_limit", 30)),
        )

    def __post_init__(self) -> None:
        if any(
            value < 1
            for value in (
                self.retention_days,
                self.max_observations_per_resource,
                self.max_total_observations,
                self.max_events_per_resource,
                self.max_events,
                self.recent_event_limit,
                self.trend_point_limit,
            )
        ):
            raise ValueError("history limits must be positive")


@dataclass(frozen=True, slots=True)
class Observation:
    resource_id: str
    resource_name: str
    status: Status
    observed_at: datetime
    metric: str = "status"
    value: float | int | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("resource_id must not be empty")
        if not self.metric:
            raise ValueError("metric must not be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class PendingNotification:
    id: int
    incident_id: int
    resource_id: str
    event_key: str
    kind: str
    message: NotificationMessage
    eligible_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class TransitionResult:
    observation_id: int
    event_id: int | None = None
    incident_id: int | None = None
    notification_id: int | None = None
    recovered: bool = False


@dataclass(frozen=True, slots=True)
class HistoryReadModel:
    recent_events: tuple[TimelineEvent, ...] = ()
    trends: tuple[TrendSeries, ...] = ()


@dataclass(frozen=True, slots=True)
class QueueStatistics:
    submitted: int
    processed: int
    dropped: int
    failed: int


_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """
            CREATE TABLE observations (
                id INTEGER PRIMARY KEY,
                resource_id TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                metric TEXT NOT NULL,
                status TEXT NOT NULL,
                value REAL,
                unit TEXT,
                observed_at TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX observations_resource_time
            ON observations(resource_id, metric, observed_at DESC, id DESC)
            """,
            """
            CREATE TABLE incidents (
                id INTEGER PRIMARY KEY,
                resource_id TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                severity TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                recovered_at TEXT
            )
            """,
            """
            CREATE INDEX incidents_resource_time
            ON incidents(resource_id, opened_at DESC, id DESC)
            """,
            """
            CREATE TABLE events (
                id INTEGER PRIMARY KEY,
                resource_id TEXT NOT NULL,
                resource_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                previous_status TEXT,
                current_status TEXT,
                incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL,
                parent_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
                recovered_at TEXT
            )
            """,
            "CREATE INDEX events_time ON events(occurred_at DESC, id DESC)",
            """
            CREATE TABLE resource_state (
                resource_id TEXT PRIMARY KEY,
                resource_name TEXT NOT NULL,
                current_status TEXT NOT NULL,
                transitioned_at TEXT NOT NULL,
                active_incident_id INTEGER REFERENCES incidents(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE TABLE notification_deliveries (
                id INTEGER PRIMARY KEY,
                incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
                resource_id TEXT NOT NULL,
                event_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK(kind IN ('failure', 'recovery')),
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                severity TEXT NOT NULL,
                icon_name TEXT NOT NULL,
                state TEXT NOT NULL
                    CHECK(state IN ('pending', 'sending', 'delivered', 'cancelled')),
                eligible_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                delivered_at TEXT,
                last_error_at TEXT
            )
            """,
            """
            CREATE INDEX notification_deliveries_due
            ON notification_deliveries(state, eligible_at, id)
            """,
        ),
    ),
)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


class HistoryStore:
    """One serialized SQLite boundary for history and delivery state."""

    def __init__(
        self,
        path: str | Path,
        *,
        limits: HistoryLimits | None = None,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self.path = str(path)
        self.limits = limits or HistoryLimits()
        self._lock = Lock()
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            self._connection = sqlite3.connect(
                self.path,
                isolation_level=None,
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._migrate()
            self.cancel_interrupted_deliveries()
        except HistoryMigrationError:
            self._connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if hasattr(self, "_connection"):
                self._connection.close()
            raise HistoryMigrationError(f"Unable to initialize history database: {exc}") from exc

    def _migrate(self) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
            current = int(row["version"])
            latest = _MIGRATIONS[-1][0]
            if current > latest:
                raise HistoryMigrationError(
                    f"History schema version {current} is newer than supported version {latest}"
                )
            for version, statements in _MIGRATIONS:
                if version <= current:
                    continue
                for statement in statements:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, _timestamp(datetime.now(UTC))),
                )
            self._connection.execute("COMMIT")
        except Exception as exc:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            if isinstance(exc, HistoryMigrationError):
                raise
            raise HistoryMigrationError(f"History migration failed: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def schema_version(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"])

    def record_observation(self, observation: Observation) -> int:
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO observations(
                    resource_id, resource_name, metric, status, value, unit, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.resource_id,
                    observation.resource_name,
                    observation.metric,
                    observation.status.value,
                    observation.value,
                    observation.unit,
                    _timestamp(observation.observed_at),
                ),
            )
            return int(cursor.lastrowid)

    def record_transition(
        self,
        observation: Observation,
        *,
        severity: Severity,
        grace: timedelta,
        notifications_enabled: bool,
        minimum_severity: Severity,
        cooldown: timedelta,
        recovery_messages: bool,
        now: datetime,
    ) -> TransitionResult:
        """Persist an observation, transition, incident, and delivery eligibility atomically."""
        severity_rank = {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}
        observed_at = _timestamp(observation.observed_at)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                observation_cursor = self._connection.execute(
                    """
                    INSERT INTO observations(
                        resource_id, resource_name, metric, status, value, unit, observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        observation.resource_id,
                        observation.resource_name,
                        observation.metric,
                        observation.status.value,
                        observation.value,
                        observation.unit,
                        observed_at,
                    ),
                )
                observation_id = int(observation_cursor.lastrowid)
                previous = self._connection.execute(
                    "SELECT * FROM resource_state WHERE resource_id = ?",
                    (observation.resource_id,),
                ).fetchone()
                previous_status = Status(previous["current_status"]) if previous else None
                active_incident_id = (
                    int(previous["active_incident_id"])
                    if previous and previous["active_incident_id"] is not None
                    else None
                )
                if previous_status == observation.status:
                    self._connection.execute(
                        "UPDATE resource_state SET resource_name = ? WHERE resource_id = ?",
                        (observation.resource_name, observation.resource_id),
                    )
                    self._connection.execute("COMMIT")
                    return TransitionResult(observation_id=observation_id)

                event_id: int | None = None
                notification_id: int | None = None
                recovered = False
                incident_id = active_incident_id
                if observation.status in {Status.DEGRADED, Status.UNAVAILABLE}:
                    if incident_id is None:
                        incident = self._connection.execute(
                            """
                            INSERT INTO incidents(
                                resource_id, resource_name, severity, opened_at
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                observation.resource_id,
                                observation.resource_name,
                                severity.value,
                                observed_at,
                            ),
                        )
                        incident_id = int(incident.lastrowid)
                    else:
                        self._connection.execute(
                            """
                            UPDATE incidents
                            SET resource_name = ?, severity = ?
                            WHERE id = ? AND recovered_at IS NULL
                            """,
                            (observation.resource_name, severity.value, incident_id),
                        )
                    active_incident_id = incident_id
                    event_id = self._insert_event(
                        observation,
                        previous_status=previous_status,
                        severity=severity,
                        event_type="failure",
                        incident_id=incident_id,
                        message=f"{observation.resource_name} is {observation.status.value}.",
                    )
                    failure_key = f"incident:{incident_id}:failure"
                    if (
                        notifications_enabled
                        and severity_rank[severity] >= severity_rank[minimum_severity]
                    ):
                        eligible_at = max(
                            observation.observed_at + grace,
                            self._cooldown_end(observation.resource_id, now, cooldown),
                        )
                        cursor = self._connection.execute(
                            """
                            INSERT INTO notification_deliveries(
                                incident_id, resource_id, event_key, kind, title, body,
                                severity, icon_name, state, eligible_at
                            ) VALUES (?, ?, ?, 'failure', ?, ?, ?, ?, 'pending', ?)
                            ON CONFLICT(event_key) DO UPDATE SET
                                title = excluded.title,
                                body = excluded.body,
                                severity = excluded.severity,
                                eligible_at = CASE
                                    WHEN notification_deliveries.state = 'pending'
                                    THEN MIN(
                                        notification_deliveries.eligible_at,
                                        excluded.eligible_at
                                    )
                                    ELSE notification_deliveries.eligible_at
                                END
                            """,
                            (
                                incident_id,
                                observation.resource_id,
                                failure_key,
                                f"{observation.resource_name}: {observation.status.value}",
                                f"{observation.resource_name} changed to "
                                f"{observation.status.value}.",
                                severity.value,
                                "server-database",
                                _timestamp(eligible_at),
                            ),
                        )
                        row = self._connection.execute(
                            "SELECT id FROM notification_deliveries WHERE event_key = ?",
                            (failure_key,),
                        ).fetchone()
                        notification_id = int(row["id"])
                elif observation.status == Status.HEALTHY and incident_id is not None:
                    recovered = True
                    self._connection.execute(
                        "UPDATE incidents SET recovered_at = ? WHERE id = ?",
                        (observed_at, incident_id),
                    )
                    self._connection.execute(
                        "UPDATE events SET recovered_at = ? WHERE incident_id = ?",
                        (observed_at, incident_id),
                    )
                    event_id = self._insert_event(
                        observation,
                        previous_status=previous_status,
                        severity=Severity.INFO,
                        event_type="recovery",
                        incident_id=incident_id,
                        message=f"{observation.resource_name} recovered.",
                        recovered_at=observed_at,
                    )
                    failure_key = f"incident:{incident_id}:failure"
                    failure_delivery = self._connection.execute(
                        """
                        SELECT state FROM notification_deliveries
                        WHERE event_key = ?
                        """,
                        (failure_key,),
                    ).fetchone()
                    self._connection.execute(
                        """
                        UPDATE notification_deliveries
                        SET state = 'cancelled'
                        WHERE event_key = ? AND state = 'pending'
                        """,
                        (failure_key,),
                    )
                    if (
                        notifications_enabled
                        and recovery_messages
                        and failure_delivery
                        and failure_delivery["state"] == "delivered"
                    ):
                        recovery_key = f"incident:{incident_id}:recovery"
                        cursor = self._connection.execute(
                            """
                            INSERT OR IGNORE INTO notification_deliveries(
                                incident_id, resource_id, event_key, kind, title, body,
                                severity, icon_name, state, eligible_at
                            ) VALUES (?, ?, ?, 'recovery', ?, ?, ?, ?, 'pending', ?)
                            """,
                            (
                                incident_id,
                                observation.resource_id,
                                recovery_key,
                                f"{observation.resource_name}: recovered",
                                f"{observation.resource_name} returned to healthy.",
                                Severity.INFO.value,
                                "server-database",
                                _timestamp(now),
                            ),
                        )
                        if cursor.lastrowid:
                            notification_id = int(cursor.lastrowid)
                    active_incident_id = None
                elif previous_status is not None:
                    event_id = self._insert_event(
                        observation,
                        previous_status=previous_status,
                        severity=Severity.INFO,
                        event_type="status",
                        incident_id=incident_id,
                        message=f"{observation.resource_name} is {observation.status.value}.",
                    )

                if previous:
                    self._connection.execute(
                        """
                        UPDATE resource_state
                        SET resource_name = ?, current_status = ?, transitioned_at = ?,
                            active_incident_id = ?
                        WHERE resource_id = ?
                        """,
                        (
                            observation.resource_name,
                            observation.status.value,
                            observed_at,
                            active_incident_id if not recovered else None,
                            observation.resource_id,
                        ),
                    )
                else:
                    self._connection.execute(
                        """
                        INSERT INTO resource_state(
                            resource_id, resource_name, current_status, transitioned_at,
                            active_incident_id
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            observation.resource_id,
                            observation.resource_name,
                            observation.status.value,
                            observed_at,
                            active_incident_id if not recovered else None,
                        ),
                    )
                self._connection.execute("COMMIT")
                return TransitionResult(
                    observation_id=observation_id,
                    event_id=event_id,
                    incident_id=incident_id,
                    notification_id=notification_id,
                    recovered=recovered,
                )
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def _insert_event(
        self,
        observation: Observation,
        *,
        previous_status: Status | None,
        severity: Severity,
        event_type: str,
        incident_id: int | None,
        message: str,
        recovered_at: str | None = None,
    ) -> int:
        cursor = self._connection.execute(
            """
            INSERT INTO events(
                resource_id, resource_name, event_type, severity, message, occurred_at,
                previous_status, current_status, incident_id, recovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation.resource_id,
                observation.resource_name,
                event_type,
                severity.value,
                message,
                _timestamp(observation.observed_at),
                previous_status.value if previous_status else None,
                observation.status.value,
                incident_id,
                recovered_at,
            ),
        )
        return int(cursor.lastrowid)

    def correlate_event(self, event_id: int, parent_event_id: int) -> None:
        """Associate a dependent event with an evidence-based parent event."""
        if event_id == parent_event_id:
            raise ValueError("an event cannot be its own parent")
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE events SET parent_event_id = ?
                WHERE id = ?
                """,
                (parent_event_id, event_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"unknown event id: {event_id}")

    def _cooldown_end(
        self,
        resource_id: str,
        now: datetime,
        cooldown: timedelta,
    ) -> datetime:
        row = self._connection.execute(
            """
            SELECT delivered_at FROM notification_deliveries
            WHERE resource_id = ? AND kind = 'failure' AND state = 'delivered'
            ORDER BY delivered_at DESC LIMIT 1
            """,
            (resource_id,),
        ).fetchone()
        return max(now, _datetime(row["delivered_at"]) + cooldown) if row else now

    def pending_notifications(
        self,
        now: datetime,
        *,
        limit: int = 64,
    ) -> tuple[PendingNotification, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM notification_deliveries
                WHERE state = 'pending' AND eligible_at <= ?
                ORDER BY eligible_at, id
                LIMIT ?
                """,
                (_timestamp(now), limit),
            ).fetchall()
        return tuple(self._pending_notification(row) for row in rows)

    def _pending_notification(self, row: sqlite3.Row) -> PendingNotification:
        severity = Severity(row["severity"])
        return PendingNotification(
            id=int(row["id"]),
            incident_id=int(row["incident_id"]),
            resource_id=row["resource_id"],
            event_key=row["event_key"],
            kind=row["kind"],
            message=NotificationMessage(
                event_key=row["event_key"],
                title=row["title"],
                body=row["body"],
                severity=severity,
                icon_name=row["icon_name"],
            ),
            eligible_at=_datetime(row["eligible_at"]),
            attempts=int(row["attempts"]),
        )

    def claim_notification(self, delivery_id: int, claimed_at: datetime) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = 'sending', claimed_at = ?, attempts = attempts + 1
                WHERE id = ? AND state = 'pending' AND eligible_at <= ?
                """,
                (_timestamp(claimed_at), delivery_id, _timestamp(claimed_at)),
            )
            return cursor.rowcount == 1

    def mark_notification_delivered(self, delivery_id: int, delivered_at: datetime) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = 'delivered', delivered_at = ?, claimed_at = NULL
                WHERE id = ? AND state = 'sending'
                """,
                (_timestamp(delivered_at), delivery_id),
            )
            return cursor.rowcount == 1

    def mark_notification_failed(
        self,
        delivery_id: int,
        failed_at: datetime,
        *,
        retry_limit: int,
        retry_delay: timedelta,
    ) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = CASE WHEN attempts >= ? THEN 'cancelled' ELSE 'pending' END,
                    eligible_at = CASE
                        WHEN attempts >= ? THEN eligible_at ELSE ?
                    END,
                    claimed_at = NULL,
                    last_error_at = ?
                WHERE id = ? AND state = 'sending'
                """,
                (
                    retry_limit,
                    retry_limit,
                    _timestamp(failed_at + retry_delay),
                    _timestamp(failed_at),
                    delivery_id,
                ),
            )
            return cursor.rowcount == 1

    def cancel_interrupted_deliveries(self) -> int:
        """Abandon unconfirmed sends after restart rather than risk duplicate delivery."""
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE notification_deliveries
                SET state = 'cancelled', claimed_at = NULL
                WHERE state = 'sending'
                """
            )
            return cursor.rowcount

    def notification_state(self, event_key: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT state FROM notification_deliveries WHERE event_key = ?",
                (event_key,),
            ).fetchone()
        return row["state"] if row else None

    def prune(self, now: datetime) -> None:
        cutoff = _timestamp(now - timedelta(days=self.limits.retention_days))
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "DELETE FROM observations WHERE observed_at < ?",
                    (cutoff,),
                )
                self._connection.execute(
                    """
                    DELETE FROM observations WHERE id IN (
                        SELECT id FROM (
                            SELECT id, ROW_NUMBER() OVER (
                                PARTITION BY resource_id, metric
                                ORDER BY observed_at DESC, id DESC
                            ) AS position
                            FROM observations
                        ) WHERE position > ?
                    )
                    """,
                    (self.limits.max_observations_per_resource,),
                )
                self._connection.execute(
                    """
                    DELETE FROM observations WHERE id IN (
                        SELECT id FROM observations
                        ORDER BY observed_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.limits.max_total_observations,),
                )
                self._connection.execute(
                    "DELETE FROM events WHERE occurred_at < ?",
                    (cutoff,),
                )
                self._connection.execute(
                    """
                    DELETE FROM events WHERE id IN (
                        SELECT id FROM (
                            SELECT id, ROW_NUMBER() OVER (
                                PARTITION BY resource_id
                                ORDER BY occurred_at DESC, id DESC
                            ) AS position
                            FROM events
                        ) WHERE position > ?
                    )
                    """,
                    (self.limits.max_events_per_resource,),
                )
                self._connection.execute(
                    """
                    DELETE FROM events WHERE id IN (
                        SELECT id FROM events
                        ORDER BY occurred_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.limits.max_events,),
                )
                self._connection.execute(
                    """
                    DELETE FROM incidents
                    WHERE recovered_at IS NOT NULL AND recovered_at < ?
                    """,
                    (cutoff,),
                )
                self._connection.execute(
                    """
                    DELETE FROM incidents WHERE id IN (
                        SELECT id FROM incidents
                        WHERE recovered_at IS NOT NULL
                        ORDER BY recovered_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (self.limits.max_events,),
                )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                table: int(
                    self._connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()[
                        "count"
                    ]
                )
                for table in ("observations", "events", "incidents", "notification_deliveries")
            }

    def read_model(self) -> HistoryReadModel:
        with self._lock:
            event_rows = self._connection.execute(
                """
                SELECT * FROM events
                ORDER BY occurred_at DESC, id DESC
                LIMIT ?
                """,
                (self.limits.recent_event_limit,),
            ).fetchall()
            trend_rows = self._connection.execute(
                """
                SELECT * FROM (
                    SELECT resource_id, resource_name, metric, unit, status, value, observed_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY resource_id, metric
                            ORDER BY observed_at DESC, id DESC
                        ) AS position
                    FROM observations
                )
                WHERE position <= ?
                ORDER BY resource_id, metric, observed_at, position DESC
                """,
                (self.limits.trend_point_limit,),
            ).fetchall()
        events = tuple(
            TimelineEvent(
                id=int(row["id"]),
                resource_id=row["resource_id"],
                resource_name=row["resource_name"],
                event_type=row["event_type"],
                severity=Severity(row["severity"]),
                message=row["message"],
                occurred_at=row["occurred_at"],
                previous_status=Status(row["previous_status"]) if row["previous_status"] else None,
                current_status=Status(row["current_status"]) if row["current_status"] else None,
                incident_id=int(row["incident_id"]) if row["incident_id"] is not None else None,
                parent_event_id=(
                    int(row["parent_event_id"]) if row["parent_event_id"] is not None else None
                ),
                recovered_at=row["recovered_at"],
            )
            for row in event_rows
        )
        grouped: dict[tuple[str, str], list[sqlite3.Row]] = {}
        for row in trend_rows:
            grouped.setdefault((row["resource_id"], row["metric"]), []).append(row)
        trends = tuple(
            TrendSeries(
                resource_id=resource_id,
                label=rows[-1]["resource_name"],
                metric=metric,
                unit=rows[-1]["unit"],
                points=[
                    TrendPoint(
                        observed_at=row["observed_at"],
                        status=Status(row["status"]),
                        value=row["value"],
                    )
                    for row in rows
                ],
            )
            for (resource_id, metric), rows in sorted(grouped.items())
        )
        return HistoryReadModel(recent_events=events, trends=trends)


class CachedHistory:
    """Thread-safe cached history projection for request paths."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._model = HistoryReadModel()

    def refresh(self, store: HistoryStore) -> None:
        model = store.read_model()
        with self._lock:
            self._model = model

    def snapshot(self) -> HistoryReadModel:
        with self._lock:
            return deepcopy(self._model)


class ObservationHandler(Protocol):
    def __call__(self, observation: Observation) -> object:
        """Persist or evaluate one observation."""


class HistoryCoordinator:
    """Drain a bounded queue without exposing SQLite latency to producers."""

    def __init__(
        self,
        store: HistoryStore,
        *,
        handler: ObservationHandler | None = None,
        queue_size: int = 512,
        clock: Clock | None = None,
        maintenance_every: int = 100,
    ) -> None:
        if queue_size < 1 or maintenance_every < 1:
            raise ValueError("queue_size and maintenance_every must be positive")
        self.store = store
        self.cache = CachedHistory()
        self._handler = handler or store.record_observation
        self._queue: queue.Queue[Observation] = queue.Queue(maxsize=queue_size)
        self._clock = clock or UtcClock()
        self._maintenance_every = maintenance_every
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._statistics_lock = Lock()
        self._submitted = 0
        self._processed = 0
        self._dropped = 0
        self._failed = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.cache.refresh(self.store)
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run,
            name="homelab-monitor-history",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout)

    def submit(self, observation: Observation) -> bool:
        try:
            self._queue.put_nowait(observation)
        except queue.Full:
            with self._statistics_lock:
                self._dropped += 1
            return False
        with self._statistics_lock:
            self._submitted += 1
        return True

    def statistics(self) -> QueueStatistics:
        with self._statistics_lock:
            return QueueStatistics(
                submitted=self._submitted,
                processed=self._processed,
                dropped=self._dropped,
                failed=self._failed,
            )

    def _run(self) -> None:
        since_maintenance = 0
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                observation = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._handler(observation)
                since_maintenance += 1
                if since_maintenance >= self._maintenance_every:
                    self.store.prune(self._clock.now())
                    since_maintenance = 0
                self.cache.refresh(self.store)
                with self._statistics_lock:
                    self._processed += 1
            except Exception:
                logger.exception("History processing failed for %s", observation.resource_id)
                with self._statistics_lock:
                    self._failed += 1
            finally:
                self._queue.task_done()
