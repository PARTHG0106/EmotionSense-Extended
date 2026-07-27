"""Request and response bodies. Distinct from the internal contracts on purpose."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from wellbeing.contracts.alerts import Explanation
from wellbeing.contracts.common import Severity


class ResidentStatus(BaseModel):
    """What the overview card renders. Severity copy is server-driven."""

    resident_id: str
    display_name: str
    severity: Severity
    severity_label: str
    current_activity: str
    zone: str | None
    since: datetime | None
    identity_confidence: float
    identity_state: str
    wellbeing_score: int | None
    risk_level: str | None
    baseline_forming: bool
    data_as_of: datetime
    notes: list[str] = Field(default_factory=list)


class AlertView(BaseModel):
    alert_id: str
    resident_id: str
    ts: datetime
    severity: Severity
    severity_label: str
    kind: str
    explanation: Explanation
    explanation_lines: list[str]
    prose: str | None
    confidence: float
    requires_human_review: bool
    suppressed_reason: str | None
    evidence_event_ids: list[str]


class AcknowledgeRequest(BaseModel):
    caregiver_id: str
    note: str = ""


class ResolveRequest(BaseModel):
    outcome: str
    was_true_positive: bool
    note: str = ""


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AskResponse(BaseModel):
    """Grounded answer. ``unanswerable_reason`` is preferred over speculation."""

    answer: str | None
    cited_event_ids: list[str] = Field(default_factory=list)
    cited_metrics: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    unanswerable_reason: str | None = None


class HealthResponse(BaseModel):
    status: str
    degradation_state: str
    cameras: dict[str, float]
    model_versions: dict[str, str]
    monitoring_reduced: bool
