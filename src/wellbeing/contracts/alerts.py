"""L4 alert contracts. The explanation schema is a data requirement, not a prompt."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from wellbeing.contracts.common import Confidence, Contract, Severity


class AlertKind(StrEnum):
    FALL = "fall"
    PROLONGED_INACTIVITY = "prolonged_inactivity"
    PROLONGED_NO_RESPONSE = "prolonged_no_response"
    NIGHT_UNRECOVERED_LYING = "night_unrecovered_lying"
    ROUTINE_DEVIATION = "routine_deviation"
    MOBILITY_DECLINE = "mobility_decline"
    REST_DISRUPTION = "rest_disruption"
    MISSED_MEAL_PATTERN = "missed_meal_pattern"
    IDENTITY_UNCERTAIN = "identity_uncertain"
    SYSTEM_DEGRADED = "system_degraded"


class Explanation(Contract):
    """The six questions every alert must answer before it may be shown.

    Fields are filled from structured upstream rows. Prose is rendered afterwards, so an
    LLM outage degrades presentation, never correctness.
    """

    what: str
    when: str
    why_flagged: str
    baseline_delta: str
    confidence: str
    check_next: str

    REQUIRED_FIELDS: tuple[str, ...] = (
        "what",
        "when",
        "why_flagged",
        "baseline_delta",
        "confidence",
        "check_next",
    )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        return tuple(
            name for name in self.REQUIRED_FIELDS if not str(getattr(self, name)).strip()
        )

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    def as_lines(self) -> tuple[str, ...]:
        return (
            f"What: {self.what}",
            f"When: {self.when}",
            f"Why flagged: {self.why_flagged}",
            f"Compared to baseline: {self.baseline_delta}",
            f"Confidence: {self.confidence}",
            f"Check next: {self.check_next}",
        )


class Alert(Contract):
    """A caregiver-facing alert.

    ``suppressed_reason`` records alerts that nearly fired. Without it, the question
    "why did we not catch this?" is unanswerable after an incident.
    """

    alert_id: str
    subject_id: str
    ts: datetime
    severity: Severity
    kind: AlertKind
    explanation: Explanation
    confidence: Confidence
    evidence_event_ids: tuple[str, ...] = ()
    anomaly_ids: tuple[str, ...] = ()
    requires_human_review: bool = False
    suppressed_reason: str | None = None
    prose: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)

    @property
    def is_actionable(self) -> bool:
        return self.suppressed_reason is None and self.severity is not Severity.NORMAL
