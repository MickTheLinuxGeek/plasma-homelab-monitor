"""Incident transition evaluation built on the durable history store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homelab_monitor.contracts import Clock
from homelab_monitor.history import HistoryStore, Observation, TransitionResult, UtcClock
from homelab_monitor.models import Severity, Status


@dataclass(frozen=True, slots=True)
class TransitionPolicy:
    notifications_enabled: bool = False
    minimum_severity: Severity = Severity.WARNING
    degraded_grace: timedelta = timedelta(seconds=60)
    unavailable_grace: timedelta = timedelta(seconds=90)
    cooldown: timedelta = timedelta(minutes=15)
    recovery_messages: bool = True

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> TransitionPolicy:
        return cls(
            notifications_enabled=bool(config.get("enabled", False)),
            minimum_severity=Severity(config.get("minimum_severity", Severity.WARNING)),
            degraded_grace=timedelta(seconds=float(config.get("degraded_grace_seconds", 60))),
            unavailable_grace=timedelta(seconds=float(config.get("unavailable_grace_seconds", 90))),
            cooldown=timedelta(seconds=float(config.get("cooldown_seconds", 900))),
            recovery_messages=bool(config.get("recovery_messages", True)),
        )

    def __post_init__(self) -> None:
        for value in (self.degraded_grace, self.unavailable_grace, self.cooldown):
            if value < timedelta(0):
                raise ValueError("notification durations must not be negative")


class IncidentEngine:
    """Evaluate transitions while delegating all state changes to one transaction."""

    def __init__(
        self,
        store: HistoryStore,
        *,
        policy: TransitionPolicy | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or TransitionPolicy()
        self.clock = clock or UtcClock()

    def process(self, observation: Observation) -> TransitionResult:
        severity = self.severity_for_status(observation.status)
        grace = self.grace_for_status(observation.status)
        return self.store.record_transition(
            observation,
            severity=severity,
            grace=grace,
            notifications_enabled=self.policy.notifications_enabled,
            minimum_severity=self.policy.minimum_severity,
            cooldown=self.policy.cooldown,
            recovery_messages=self.policy.recovery_messages,
            now=self.clock.now(),
        )

    __call__ = process

    def grace_for_status(self, status: Status) -> timedelta:
        if status == Status.DEGRADED:
            return self.policy.degraded_grace
        if status == Status.UNAVAILABLE:
            return self.policy.unavailable_grace
        return timedelta(0)

    @staticmethod
    def severity_for_status(status: Status) -> Severity:
        if status == Status.UNAVAILABLE:
            return Severity.CRITICAL
        if status == Status.DEGRADED:
            return Severity.WARNING
        return Severity.INFO
