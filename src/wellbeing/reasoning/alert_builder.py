"""Alert assembly: severity, suppression, review requirements and rate limiting."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime

from wellbeing.config import AlertsConfig, ReasoningConfig
from wellbeing.contracts.activity import ActivityEvent, FallAssessment
from wellbeing.contracts.alerts import Alert, AlertKind, Explanation
from wellbeing.contracts.behavior import AnomalySignal, TrendResult
from wellbeing.contracts.common import Severity
from wellbeing.contracts.perception import IdentityAssignment
from wellbeing.reasoning.explainer import Explainer, GroundingViolation

_ANOMALY_KIND_BY_METRIC: dict[str, AlertKind] = {
    "active_minutes": AlertKind.ROUTINE_DEVIATION,
    "walking_minutes": AlertKind.MOBILITY_DECLINE,
    "walking_bouts": AlertKind.MOBILITY_DECLINE,
    "sit_to_stand_transitions": AlertKind.MOBILITY_DECLINE,
    "longest_inactive_minutes": AlertKind.PROLONGED_INACTIVITY,
    "lying_minutes": AlertKind.REST_DISRUPTION,
    "meal_events": AlertKind.MISSED_MEAL_PATTERN,
    "zone_changes": AlertKind.ROUTINE_DEVIATION,
}


class AlertBuilder:
    """Converts structured signals into caregiver alerts."""

    def __init__(
        self,
        alerts_config: AlertsConfig,
        reasoning_config: ReasoningConfig,
        explainer: Explainer | None = None,
    ) -> None:
        self._alerts = alerts_config
        self._reasoning = reasoning_config
        self._explainer = explainer or Explainer(reasoning_config)
        self._counts: dict[tuple[str, date], int] = defaultdict(int)

    # ---------------------------------------------------------------------- fall
    def from_fall(
        self,
        event: ActivityEvent,
        assessment: FallAssessment,
        identity: IdentityAssignment | None = None,
    ) -> Alert:
        """Fall alerts are critical and are never rate limited or auto-closed."""
        explanation = self._explainer.for_fall(event, assessment, identity)
        return self._finalise(
            subject_id=event.subject_id,
            ts=event.window.end,
            severity=Severity.CRITICAL,
            kind=AlertKind.FALL,
            explanation=explanation,
            confidence=assessment.confidence,
            evidence_event_ids=(event.event_id,),
            model_versions=event.model_versions,
        )

    # ------------------------------------------------------------------- anomaly
    def from_anomaly(
        self,
        anomaly: AnomalySignal,
        identity: IdentityAssignment | None = None,
        trend: TrendResult | None = None,
        consecutive_days: int = 0,
        sustained_threshold: int = 7,
    ) -> Alert:
        kind = _ANOMALY_KIND_BY_METRIC.get(anomaly.metric, AlertKind.ROUTINE_DEVIATION)
        explanation = self._explainer.for_anomaly(anomaly, kind, identity, trend)
        severity = anomaly.severity
        suppressed: str | None = None

        if identity is not None and not identity.supports_behavior_claims(
            self._reasoning.identity_confidence_floor
        ):
            # Attributing behaviour to the wrong resident is worse than staying quiet.
            suppressed = (
                f"identity confidence {identity.confidence:.0%} below the "
                f"{self._reasoning.identity_confidence_floor:.0%} floor"
            )
        elif consecutive_days >= sustained_threshold:
            # Re-alerting daily on the same change is how caregivers learn to ignore it.
            suppressed = (
                f"deviation sustained for {consecutive_days} days; reported as a trend "
                "instead of a repeated daily alert"
            )
        elif self._is_rate_limited(anomaly.subject_id, anomaly.window.start, kind):
            suppressed = "daily alert cap for this resident already reached"

        return self._finalise(
            subject_id=anomaly.subject_id,
            ts=anomaly.window.end,
            severity=severity,
            kind=kind,
            explanation=explanation,
            confidence=anomaly.score,
            anomaly_ids=(anomaly.anomaly_id,),
            evidence_event_ids=anomaly.evidence_event_ids,
            suppressed_reason=suppressed,
        )

    # ------------------------------------------------------------------ internals
    def _is_rate_limited(self, subject_id: str, moment: datetime, kind: AlertKind) -> bool:
        if kind.value in self._alerts.never_rate_limit:
            return False
        return self._counts[(subject_id, moment.date())] >= 3

    def _finalise(
        self,
        subject_id: str,
        ts: datetime,
        severity: Severity,
        kind: AlertKind,
        explanation: Explanation,
        confidence: float,
        evidence_event_ids: tuple[str, ...] = (),
        anomaly_ids: tuple[str, ...] = (),
        suppressed_reason: str | None = None,
        model_versions: dict[str, str] | None = None,
    ) -> Alert:
        try:
            prose: str | None = self._explainer.render_prose(explanation)
        except GroundingViolation:
            # Ship the structured card rather than unvalidated text.
            prose = None
        if suppressed_reason is None:
            self._counts[(subject_id, ts.date())] += 1
        return Alert(
            alert_id=f"alrt_{uuid.uuid4().hex[:16]}",
            subject_id=subject_id,
            ts=ts,
            severity=severity,
            kind=kind,
            explanation=explanation,
            confidence=max(0.0, min(1.0, confidence)),
            evidence_event_ids=evidence_event_ids,
            anomaly_ids=anomaly_ids,
            requires_human_review=severity.requires_human_review,
            suppressed_reason=suppressed_reason,
            prose=prose,
            model_versions=model_versions or {},
        )
