"""Postgres-backed implementation of the API query surface.

Method signatures match :class:`wellbeing.api.repository.Repository` exactly, so
``create_app(config, SqlRepository(engine))`` works with no route changes.

Two rules are enforced here rather than left to callers:

1. **Every read of resident data writes an audit row.** The audit table rejects UPDATE and
   DELETE at the database level, so the trail cannot be quietly rewritten.
2. **Rows that violate a contract are dropped, not coerced.** A malformed row surfaces as
   missing data, which is visible, rather than as a fabricated event, which is not.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import Engine, text

from wellbeing.api.repository import AuditEntry, Resident
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, EventSource
from wellbeing.contracts.alerts import Alert, AlertKind, Explanation
from wellbeing.contracts.behavior import (
    BehaviorProfile,
    Bucket,
    DailyFeatures,
    RiskLevel,
    TrendDirection,
    TrendResult,
)
from wellbeing.contracts.common import Severity, SubjectKind, TimeWindow

logger = logging.getLogger(__name__)


class SqlRepository:
    """Read/write repository over the schema in ``sql/schema.sql``."""

    def __init__(self, engine: Engine, *, actor_role: str = "service") -> None:
        self._engine = engine
        self._actor_role = actor_role

    # ------------------------------------------------------------------- auditing
    def audit(
        self,
        actor_id: str,
        action: str,
        resident_id: str | None,
        purpose: str,
        *,
        target: str | None = None,
        actor_role: str | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit.access_log "
                    "(actor_id, actor_role, action, resident_id, target, purpose) "
                    "VALUES (:actor_id, :actor_role, :action, :resident_id, :target, :purpose)"
                ),
                {
                    "actor_id": actor_id,
                    "actor_role": actor_role or self._actor_role,
                    "action": action,
                    "resident_id": resident_id,
                    "target": target,
                    "purpose": purpose,
                },
            )

    def audit_trail(self, resident_id: str | None = None, limit: int = 200) -> list[AuditEntry]:
        query = text(
            "SELECT ts, actor_id, action, resident_id, purpose FROM audit.access_log "
            "WHERE (:resident_id IS NULL OR resident_id = :resident_id) "
            "ORDER BY ts DESC LIMIT :limit"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query, {"resident_id": resident_id, "limit": limit}).mappings()
            return [
                AuditEntry(
                    ts=row["ts"],
                    actor_id=row["actor_id"],
                    action=row["action"],
                    resident_id=row["resident_id"],
                    purpose=row["purpose"],
                )
                for row in rows
            ]

    # -------------------------------------------------------------------- residents
    def residents(self) -> list[Resident]:
        query = text(
            "SELECT resident_id, display_name, room FROM identity.resident "
            "WHERE active AND consent_status = 'granted' ORDER BY display_name"
        )
        with self._engine.connect() as connection:
            return [
                Resident(resident_id=r["resident_id"], display_name=r["display_name"], room=r["room"])
                for r in connection.execute(query).mappings()
            ]

    def resident(self, resident_id: str) -> Resident | None:
        query = text(
            "SELECT resident_id, display_name, room FROM identity.resident "
            "WHERE resident_id = :resident_id AND active"
        )
        with self._engine.connect() as connection:
            row = connection.execute(query, {"resident_id": resident_id}).mappings().first()
        if row is None:
            return None
        return Resident(resident_id=row["resident_id"], display_name=row["display_name"], room=row["room"])

    # ----------------------------------------------------------------------- events
    def events(
        self,
        resident_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        label: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 200,
    ) -> list[ActivityEvent]:
        # Overlap semantics, not containment: an event straddling the window boundary is still
        # relevant to the caregiver asking about that window.
        query = text(
            "SELECT * FROM events.activity_event WHERE subject_id = :subject_id "
            "AND confidence >= :min_confidence "
            "AND (:start IS NULL OR ended_at >= :start) "
            "AND (:end IS NULL OR started_at <= :end) "
            "AND (:label IS NULL OR label = :label) "
            "ORDER BY started_at DESC LIMIT :limit"
        )
        params = {
            "subject_id": resident_id,
            "min_confidence": min_confidence,
            "start": start,
            "end": end,
            "label": label,
            "limit": limit,
        }
        with self._engine.connect() as connection:
            rows = connection.execute(query, params).mappings().all()
        return [event for event in (self._to_event(r) for r in rows) if event is not None]

    def add_events(self, events: Sequence[ActivityEvent]) -> None:
        if not events:
            return
        statement = text(
            "INSERT INTO events.activity_event "
            "(event_id, subject_id, subject_kind, camera_id, zone, label, started_at, ended_at, "
            " confidence, identity_confidence, source, evidence, model_versions) "
            "VALUES (:event_id, :subject_id, :subject_kind, :camera_id, :zone, :label, "
            " :started_at, :ended_at, :confidence, :identity_confidence, :source, "
            " CAST(:evidence AS JSONB), CAST(:model_versions AS JSONB)) "
            "ON CONFLICT (event_id, started_at) DO NOTHING"
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement,
                [
                    {
                        "event_id": e.event_id,
                        "subject_id": e.subject_id,
                        "subject_kind": e.subject_kind.value,
                        "camera_id": e.camera_id,
                        "zone": e.zone,
                        "label": e.label.value,
                        "started_at": e.window.start,
                        "ended_at": e.window.end,
                        "confidence": e.confidence,
                        "identity_confidence": e.identity_confidence,
                        "source": e.source.value,
                        "evidence": json.dumps(list(e.evidence)),
                        "model_versions": json.dumps(e.model_versions),
                    }
                    for e in events
                ],
            )

    # ----------------------------------------------------------------------- alerts
    def alerts(
        self,
        resident_id: str | None = None,
        severity: str | None = None,
        include_suppressed: bool = False,
    ) -> list[Alert]:
        query = text(
            "SELECT * FROM events.alert "
            "WHERE (:subject_id IS NULL OR subject_id = :subject_id) "
            "AND (:severity IS NULL OR severity = :severity) "
            "AND (:include_suppressed OR suppressed_reason IS NULL) "
            "ORDER BY CASE severity WHEN 'critical' THEN 3 WHEN 'warning' THEN 2 "
            "  WHEN 'attention' THEN 1 ELSE 0 END DESC, ts DESC"
        )
        params = {
            "subject_id": resident_id,
            "severity": severity,
            "include_suppressed": include_suppressed,
        }
        with self._engine.connect() as connection:
            rows = connection.execute(query, params).mappings().all()
        return [alert for alert in (self._to_alert(r) for r in rows) if alert is not None]

    def alert(self, alert_id: str) -> Alert | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM events.alert WHERE alert_id = :alert_id"),
                    {"alert_id": alert_id},
                )
                .mappings()
                .first()
            )
        return self._to_alert(row) if row is not None else None

    def add_alerts(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        statement = text(
            "INSERT INTO events.alert "
            "(alert_id, subject_id, ts, severity, kind, exp_what, exp_when, exp_why_flagged, "
            " exp_baseline_delta, exp_confidence, exp_check_next, prose, confidence, "
            " evidence_event_ids, anomaly_ids, requires_human_review, suppressed_reason, model_versions) "
            "VALUES (:alert_id, :subject_id, :ts, :severity, :kind, :exp_what, :exp_when, "
            " :exp_why_flagged, :exp_baseline_delta, :exp_confidence, :exp_check_next, :prose, "
            " :confidence, :evidence_event_ids, :anomaly_ids, :requires_human_review, "
            " :suppressed_reason, CAST(:model_versions AS JSONB)) "
            "ON CONFLICT (alert_id) DO NOTHING"
        )
        payload: list[dict[str, Any]] = []
        for alert in alerts:
            # The DB CHECK would reject this anyway; failing here names the offending alert.
            if not alert.explanation.is_complete:
                raise ValueError(
                    f"alert {alert.alert_id} is missing explanation fields "
                    f"{alert.explanation.missing_fields}; it must not be persisted or shown"
                )
            payload.append(
                {
                    "alert_id": alert.alert_id,
                    "subject_id": alert.subject_id,
                    "ts": alert.ts,
                    "severity": alert.severity.value,
                    "kind": alert.kind.value,
                    "exp_what": alert.explanation.what,
                    "exp_when": alert.explanation.when,
                    "exp_why_flagged": alert.explanation.why_flagged,
                    "exp_baseline_delta": alert.explanation.baseline_delta,
                    "exp_confidence": alert.explanation.confidence,
                    "exp_check_next": alert.explanation.check_next,
                    "prose": alert.prose,
                    "confidence": alert.confidence,
                    "evidence_event_ids": list(alert.evidence_event_ids),
                    "anomaly_ids": list(alert.anomaly_ids),
                    "requires_human_review": alert.requires_human_review,
                    "suppressed_reason": alert.suppressed_reason,
                    "model_versions": json.dumps(alert.model_versions),
                }
            )
        with self._engine.begin() as connection:
            connection.execute(statement, payload)

    def record_acknowledgement(
        self, alert_id: str, actor_id: str, note: str, was_true_positive: bool | None = None
    ) -> None:
        statement = text(
            "INSERT INTO events.alert_feedback "
            "(alert_id, actor_id, acknowledged_at, was_true_positive, note) "
            "VALUES (:alert_id, :actor_id, now(), :was_true_positive, :note)"
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "alert_id": alert_id,
                    "actor_id": actor_id,
                    "was_true_positive": was_true_positive,
                    "note": note,
                },
            )

    # ------------------------------------------------------------------- aggregates
    def features(self, resident_id: str, day: date | None = None) -> list[DailyFeatures]:
        query = text(
            "SELECT subject_id, day, bucket, features, completeness FROM events.daily_feature "
            "WHERE subject_id = :subject_id AND (:day IS NULL OR day = :day) "
            "ORDER BY day DESC, bucket"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query, {"subject_id": resident_id, "day": day}).mappings().all()
        results: list[DailyFeatures] = []
        for row in rows:
            features = row["features"]
            results.append(
                DailyFeatures(
                    subject_id=row["subject_id"],
                    day=row["day"],
                    bucket=Bucket(row["bucket"]),
                    features={k: float(v) for k, v in (json.loads(features) if isinstance(features, str) else features).items()},
                    completeness=float(row["completeness"]),
                )
            )
        return results

    def trends(self, resident_id: str, metric: str | None = None) -> list[TrendResult]:
        # Latest computation per metric only: older rows are history, not current state.
        query = text(
            "SELECT DISTINCT ON (metric) subject_id, metric, window_days, direction, "
            "  slope_per_day, p_value, n_points, statement "
            "FROM events.behavior_trend "
            "WHERE subject_id = :subject_id AND (:metric IS NULL OR metric = :metric) "
            "ORDER BY metric, computed_on DESC"
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query, {"subject_id": resident_id, "metric": metric}).mappings().all()
        return [
            TrendResult(
                subject_id=row["subject_id"],
                metric=row["metric"],
                window_days=row["window_days"],
                direction=TrendDirection(row["direction"]),
                slope_per_day=float(row["slope_per_day"]),
                p_value=float(row["p_value"]),
                n_points=row["n_points"],
                statement=row["statement"] or "",
            )
            for row in rows
        ]

    def add_trends(self, trends: Sequence[TrendResult], computed_on: date | None = None) -> None:
        if not trends:
            return
        statement = text(
            "INSERT INTO events.behavior_trend "
            "(subject_id, metric, computed_on, window_days, direction, slope_per_day, "
            " p_value, n_points, statement) "
            "VALUES (:subject_id, :metric, :computed_on, :window_days, :direction, "
            " :slope_per_day, :p_value, :n_points, :statement) "
            "ON CONFLICT (subject_id, metric, computed_on) DO UPDATE SET "
            " window_days = EXCLUDED.window_days, direction = EXCLUDED.direction, "
            " slope_per_day = EXCLUDED.slope_per_day, p_value = EXCLUDED.p_value, "
            " n_points = EXCLUDED.n_points, statement = EXCLUDED.statement"
        )
        day = computed_on or date.today()
        with self._engine.begin() as connection:
            connection.execute(
                statement,
                [
                    {
                        "subject_id": t.subject_id,
                        "metric": t.metric,
                        "computed_on": day,
                        "window_days": t.window_days,
                        "direction": t.direction.value,
                        "slope_per_day": t.slope_per_day,
                        "p_value": t.p_value,
                        "n_points": t.n_points,
                        "statement": t.statement,
                    }
                    for t in trends
                ],
            )

    def profile(self, resident_id: str) -> BehaviorProfile | None:
        query = text(
            "SELECT subject_id, generated_at, wellbeing_score, risk_level, components, "
            "  baseline_forming FROM events.behavior_profile "
            "WHERE subject_id = :subject_id ORDER BY generated_at DESC LIMIT 1"
        )
        with self._engine.connect() as connection:
            row = connection.execute(query, {"subject_id": resident_id}).mappings().first()
        if row is None:
            return None
        components = row["components"]
        return BehaviorProfile(
            subject_id=row["subject_id"],
            generated_at=row["generated_at"],
            wellbeing_score=int(row["wellbeing_score"]),
            risk_level=RiskLevel(row["risk_level"]),
            components={
                k: float(v)
                for k, v in (json.loads(components) if isinstance(components, str) else components).items()
            },
            baseline_forming=bool(row["baseline_forming"]),
            # Baselines, trends and anomalies are loaded on demand by the report endpoints
            # rather than eagerly here; a status card does not need them.
            trends=tuple(self.trends(resident_id)),
        )

    def save_profile(self, profile: BehaviorProfile) -> None:
        statement = text(
            "INSERT INTO events.behavior_profile "
            "(subject_id, generated_at, wellbeing_score, risk_level, components, baseline_forming) "
            "VALUES (:subject_id, :generated_at, :wellbeing_score, :risk_level, "
            " CAST(:components AS JSONB), :baseline_forming) "
            "ON CONFLICT (subject_id, generated_at) DO NOTHING"
        )
        with self._engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "subject_id": profile.subject_id,
                    "generated_at": profile.generated_at,
                    "wellbeing_score": profile.wellbeing_score,
                    "risk_level": profile.risk_level.value,
                    "components": json.dumps(profile.components),
                    "baseline_forming": profile.baseline_forming,
                },
            )

    # ---------------------------------------------------------------------- mapping
    def _to_event(self, row: Any) -> ActivityEvent | None:
        try:
            evidence = row["evidence"]
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            versions = row["model_versions"] or {}
            if isinstance(versions, str):
                versions = json.loads(versions)
            return ActivityEvent(
                event_id=row["event_id"],
                subject_id=row["subject_id"],
                subject_kind=SubjectKind(row["subject_kind"]),
                camera_id=row["camera_id"],
                zone=row["zone"],
                label=ActivityLabel(row["label"]),
                window=TimeWindow(start=row["started_at"], end=row["ended_at"]),
                confidence=float(row["confidence"]),
                identity_confidence=float(row["identity_confidence"]),
                source=EventSource(row["source"]),
                evidence=tuple(evidence),
                model_versions={str(k): str(v) for k, v in versions.items()},
            )
        except Exception:
            # Dropped, not coerced: a fabricated event would be cited as evidence in an
            # explanation and there would be no way to tell it apart from a real one.
            logger.exception("dropping malformed activity_event row %s", row.get("event_id"))
            return None

    def _to_alert(self, row: Any) -> Alert | None:
        try:
            versions = row["model_versions"] or {}
            if isinstance(versions, str):
                versions = json.loads(versions)
            return Alert(
                alert_id=row["alert_id"],
                subject_id=row["subject_id"],
                ts=row["ts"],
                severity=Severity(row["severity"]),
                kind=AlertKind(row["kind"]),
                explanation=Explanation(
                    what=row["exp_what"],
                    when=row["exp_when"],
                    why_flagged=row["exp_why_flagged"],
                    baseline_delta=row["exp_baseline_delta"],
                    confidence=row["exp_confidence"],
                    check_next=row["exp_check_next"],
                ),
                confidence=float(row["confidence"]),
                evidence_event_ids=tuple(row["evidence_event_ids"] or ()),
                anomaly_ids=tuple(row["anomaly_ids"] or ()),
                requires_human_review=bool(row["requires_human_review"]),
                suppressed_reason=row["suppressed_reason"],
                prose=row["prose"],
                model_versions={str(k): str(v) for k, v in versions.items()},
            )
        except Exception:
            logger.exception("dropping malformed alert row %s", row.get("alert_id"))
            return None
