"""Read models backed by an in-memory store.

The production implementation is the SQLAlchemy repository over the schema in
``sql/schema.sql``; the interface is identical, which keeps the API and its tests runnable
with no database. Audit writes are not optional in either implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from wellbeing.contracts.activity import ActivityEvent
from wellbeing.contracts.alerts import Alert
from wellbeing.contracts.behavior import BehaviorProfile, DailyFeatures, TrendResult


@dataclass(frozen=True, slots=True)
class Resident:
    resident_id: str
    display_name: str
    room: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    ts: datetime
    actor_id: str
    action: str
    resident_id: str | None
    purpose: str


@dataclass
class Store:
    """Append-mostly in-memory store."""

    residents: dict[str, Resident] = field(default_factory=dict)
    events: list[ActivityEvent] = field(default_factory=list)
    alerts: dict[str, Alert] = field(default_factory=dict)
    features: list[DailyFeatures] = field(default_factory=list)
    trends: list[TrendResult] = field(default_factory=list)
    profiles: dict[str, BehaviorProfile] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    acknowledgements: dict[str, dict[str, object]] = field(default_factory=dict)


class Repository:
    """Query surface used by the API layer."""

    def __init__(self, store: Store | None = None) -> None:
        self._store = store or Store()

    @property
    def store(self) -> Store:
        return self._store

    # ------------------------------------------------------------------- auditing
    def audit(self, actor_id: str, action: str, resident_id: str | None, purpose: str) -> None:
        """Append-only. Identity and media access must always leave a trace."""
        self._store.audit.append(
            AuditEntry(
                ts=datetime.now(),
                actor_id=actor_id,
                action=action,
                resident_id=resident_id,
                purpose=purpose,
            )
        )

    # ------------------------------------------------------------------- queries
    def residents(self) -> list[Resident]:
        return list(self._store.residents.values())

    def resident(self, resident_id: str) -> Resident | None:
        return self._store.residents.get(resident_id)

    def events(
        self,
        resident_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        label: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 200,
    ) -> list[ActivityEvent]:
        selected = [
            e
            for e in self._store.events
            if e.subject_id == resident_id
            and e.confidence >= min_confidence
            and (start is None or e.window.end >= start)
            and (end is None or e.window.start <= end)
            and (label is None or e.label.value == label)
        ]
        selected.sort(key=lambda e: e.window.start, reverse=True)
        return selected[:limit]

    def alerts(
        self,
        resident_id: str | None = None,
        severity: str | None = None,
        include_suppressed: bool = False,
    ) -> list[Alert]:
        selected = [
            a
            for a in self._store.alerts.values()
            if (resident_id is None or a.subject_id == resident_id)
            and (severity is None or a.severity.value == severity)
            and (include_suppressed or a.suppressed_reason is None)
        ]
        selected.sort(key=lambda a: (a.severity.rank, a.ts), reverse=True)
        return selected

    def alert(self, alert_id: str) -> Alert | None:
        return self._store.alerts.get(alert_id)

    def features(self, resident_id: str, day: date | None = None) -> list[DailyFeatures]:
        return [
            f
            for f in self._store.features
            if f.subject_id == resident_id and (day is None or f.day == day)
        ]

    def trends(self, resident_id: str, metric: str | None = None) -> list[TrendResult]:
        return [
            t
            for t in self._store.trends
            if t.subject_id == resident_id and (metric is None or t.metric == metric)
        ]

    def profile(self, resident_id: str) -> BehaviorProfile | None:
        return self._store.profiles.get(resident_id)

    def record_acknowledgement(
        self, alert_id: str, actor_id: str, note: str, was_true_positive: bool | None = None
    ) -> None:
        """Caregiver feedback is the only ground truth a deployment ever produces.

        Per-resident threshold recalibration depends entirely on this field, which is why
        it is a first-class write and not a free-text note.
        """
        self._store.acknowledgements[alert_id] = {
            "actor_id": actor_id,
            "note": note,
            "was_true_positive": was_true_positive,
            "ts": datetime.now(),
        }

    def add_events(self, events: Sequence[ActivityEvent]) -> None:
        self._store.events.extend(events)

    def add_alerts(self, alerts: Sequence[Alert]) -> None:
        for alert in alerts:
            self._store.alerts[alert.alert_id] = alert
