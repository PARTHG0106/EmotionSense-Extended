"""FastAPI application.

The API is a thin projection of the contracts. Two rules are enforced here rather than in
the frontend: severity copy and identity gating are server-driven, so a client can never
present an unreviewed or unattributable claim as fact.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from wellbeing.api.repository import Repository
from wellbeing.api.schemas import (
    AcknowledgeRequest,
    AlertView,
    AskRequest,
    AskResponse,
    HealthResponse,
    ResidentStatus,
    ResolveRequest,
)
from wellbeing.api.security import Principal, Scope, current_principal
from wellbeing.config import AppConfig, load_config
from wellbeing.contracts.alerts import Alert
from wellbeing.contracts.common import Severity

SEVERITY_LABELS: dict[Severity, str] = {
    Severity.NORMAL: "Normal",
    Severity.ATTENTION: "Attention",
    Severity.WARNING: "Warning",
    Severity.CRITICAL: "Critical",
}


def _alert_view(alert: Alert) -> AlertView:
    return AlertView(
        alert_id=alert.alert_id,
        resident_id=alert.subject_id,
        ts=alert.ts,
        severity=alert.severity,
        severity_label=SEVERITY_LABELS[alert.severity],
        kind=alert.kind.value,
        explanation=alert.explanation,
        explanation_lines=list(alert.explanation.as_lines()),
        prose=alert.prose,
        confidence=alert.confidence,
        requires_human_review=alert.requires_human_review,
        suppressed_reason=alert.suppressed_reason,
        evidence_event_ids=list(alert.evidence_event_ids),
    )


def create_app(config: AppConfig | None = None, repository: Repository | None = None) -> FastAPI:
    app_config = config or load_config()
    repo = repository or Repository()
    app = FastAPI(
        title="Well-being monitoring API",
        version="0.1.0",
        description=(
            "Caregiver decision support. This service reports observations and risk "
            "signals; it does not diagnose or prescribe."
        ),
    )
    app.state.config = app_config
    app.state.repository = repo

    PrincipalDep = Annotated[Principal, Depends(current_principal)]

    # ------------------------------------------------------------------ residents
    @app.get("/v1/residents", response_model=list[ResidentStatus])
    def list_residents(principal: PrincipalDep) -> list[ResidentStatus]:
        principal.require(Scope.READ_STATUS)
        return [
            _status_for(repo, app_config, r.resident_id)
            for r in repo.residents()
            if principal.role.value == "admin" or r.resident_id in principal.resident_ids
        ]

    @app.get("/v1/residents/{resident_id}/status", response_model=ResidentStatus)
    def resident_status(resident_id: str, principal: PrincipalDep) -> ResidentStatus:
        principal.require(Scope.READ_STATUS)
        principal.require_resident(resident_id)
        if repo.resident(resident_id) is None:
            raise HTTPException(status_code=404, detail="resident not found")
        return _status_for(repo, app_config, resident_id)

    # --------------------------------------------------------------------- events
    @app.get("/v1/events")
    def list_events(
        principal: PrincipalDep,
        resident_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
        label: str | None = None,
        min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, object]:
        principal.require(Scope.READ_EVENTS)
        principal.require_resident(resident_id)
        events = repo.events(resident_id, start, end, label, min_confidence, limit)
        return {"results": [e.model_dump(mode="json") for e in events], "count": len(events)}

    # --------------------------------------------------------------------- alerts
    @app.get("/v1/alerts", response_model=list[AlertView])
    def list_alerts(
        principal: PrincipalDep,
        resident_id: str | None = None,
        severity: str | None = None,
        include_suppressed: bool = False,
    ) -> list[AlertView]:
        principal.require(Scope.READ_EVENTS)
        if resident_id is not None:
            principal.require_resident(resident_id)
        return [
            _alert_view(a) for a in repo.alerts(resident_id, severity, include_suppressed)
        ]

    @app.get("/v1/alerts/{alert_id}", response_model=AlertView)
    def get_alert(alert_id: str, principal: PrincipalDep) -> AlertView:
        principal.require(Scope.READ_EVENTS)
        alert = repo.alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="alert not found")
        principal.require_resident(alert.subject_id)
        return _alert_view(alert)

    @app.post("/v1/alerts/{alert_id}/acknowledge", response_model=AlertView)
    def acknowledge(
        alert_id: str, body: AcknowledgeRequest, principal: PrincipalDep
    ) -> AlertView:
        principal.require(Scope.WRITE_ALERTS)
        alert = repo.alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="alert not found")
        principal.require_resident(alert.subject_id)
        repo.record_acknowledgement(alert_id, principal.actor_id, body.note)
        repo.audit(principal.actor_id, "alert.acknowledge", alert.subject_id, "shift response")
        return _alert_view(alert)

    @app.post("/v1/alerts/{alert_id}/resolve", response_model=AlertView)
    def resolve(alert_id: str, body: ResolveRequest, principal: PrincipalDep) -> AlertView:
        principal.require(Scope.WRITE_ALERTS)
        alert = repo.alert(alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="alert not found")
        principal.require_resident(alert.subject_id)
        repo.record_acknowledgement(
            alert_id, principal.actor_id, body.note, was_true_positive=body.was_true_positive
        )
        repo.audit(principal.actor_id, "alert.resolve", alert.subject_id, body.outcome)
        return _alert_view(alert)

    # ------------------------------------------------------------------- behaviour
    @app.get("/v1/residents/{resident_id}/behavior/trends")
    def trends(
        resident_id: str, principal: PrincipalDep, metric: str | None = None
    ) -> dict[str, object]:
        principal.require(Scope.READ_REPORTS)
        principal.require_resident(resident_id)
        results = repo.trends(resident_id, metric)
        return {"results": [t.model_dump(mode="json") for t in results]}

    @app.get("/v1/residents/{resident_id}/reports/daily")
    def daily_report(
        resident_id: str, principal: PrincipalDep, day: date | None = None
    ) -> dict[str, object]:
        principal.require(Scope.READ_REPORTS)
        principal.require_resident(resident_id)
        features = repo.features(resident_id, day)
        if not features:
            raise HTTPException(status_code=404, detail="no aggregates for that day")
        completeness = min(f.completeness for f in features)
        return {
            "resident_id": resident_id,
            "day": (day or features[0].day).isoformat(),
            "buckets": [f.model_dump(mode="json") for f in features],
            "data_completeness": completeness,
            # Stated explicitly so a partial day is never read as a quiet day.
            "coverage_note": (
                "Camera coverage was incomplete for part of this day."
                if completeness < 1.0
                else "Full camera coverage."
            ),
        }

    # ------------------------------------------------------------- grounded Q and A
    @app.post("/v1/residents/{resident_id}/ask", response_model=AskResponse)
    def ask(resident_id: str, body: AskRequest, principal: PrincipalDep) -> AskResponse:
        principal.require(Scope.READ_REPORTS)
        principal.require_resident(resident_id)
        trends_available = repo.trends(resident_id)
        features_available = repo.features(resident_id)
        if not trends_available and not features_available:
            return AskResponse(
                answer=None,
                unanswerable_reason=(
                    "No stored aggregates cover that question yet. Answering would require "
                    "speculation."
                ),
            )
        matched = [
            t for t in trends_available if t.metric.split("_")[0] in body.question.lower()
        ]
        if not matched:
            return AskResponse(
                answer=None,
                cited_metrics=[t.metric for t in trends_available],
                unanswerable_reason=(
                    "That question does not map to a metric this system records."
                ),
            )
        return AskResponse(
            answer=" ".join(t.statement for t in matched),
            cited_metrics=[t.metric for t in matched],
            confidence=0.8,
        )

    # ------------------------------------------------------------------------ ops
    @app.get("/v1/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            degradation_state=app_config.runtime.degradation_ladder[0],
            cameras={c.camera_id: float(c.fps_target) for c in app_config.cameras},
            model_versions={
                "detector": app_config.perception.detector.backend,
                "pose": app_config.perception.pose.backend,
                "reid": app_config.perception.reid.backend,
            },
            monitoring_reduced=False,
        )

    return app


def _status_for(repo: Repository, config: AppConfig, resident_id: str) -> ResidentStatus:
    resident = repo.resident(resident_id)
    display_name = resident.display_name if resident else resident_id
    events = repo.events(resident_id, limit=1)
    latest = events[0] if events else None
    open_alerts = repo.alerts(resident_id)
    severity = max(
        (a.severity for a in open_alerts), key=lambda s: s.rank, default=Severity.NORMAL
    )
    profile = repo.profile(resident_id)
    identity_confidence = latest.identity_confidence if latest else 0.0
    floor = config.reasoning.identity_confidence_floor
    trustworthy = identity_confidence >= floor
    notes: list[str] = []
    if not trustworthy:
        # The UI greys out behavioural claims when this is present.
        notes.append(
            "Identity confidence is below the reporting threshold; behavioural "
            "comparisons are withheld."
        )
    if profile is not None and profile.baseline_forming:
        notes.append("Baseline is still forming; deviation alerts are suppressed.")
    return ResidentStatus(
        resident_id=resident_id,
        display_name=display_name,
        severity=severity,
        severity_label=SEVERITY_LABELS[severity],
        current_activity=latest.label.value.replace("_", " ") if latest else "no recent data",
        zone=latest.zone if latest else None,
        since=latest.window.start if latest else None,
        identity_confidence=identity_confidence,
        identity_state="confirmed" if trustworthy else "uncertain",
        wellbeing_score=profile.wellbeing_score if profile and trustworthy else None,
        risk_level=profile.risk_level.value if profile and trustworthy else None,
        baseline_forming=bool(profile and profile.baseline_forming),
        data_as_of=datetime.now(),
        notes=notes,
    )
