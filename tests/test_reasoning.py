from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from wellbeing.config import AlertsConfig, ReasoningConfig
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, EventSource, FallAssessment
from wellbeing.contracts.alerts import AlertKind, Explanation
from wellbeing.contracts.behavior import AnomalyMethod, AnomalySignal, Bucket
from wellbeing.contracts.common import Severity, SubjectKind, TimeWindow
from wellbeing.contracts.perception import IdentityAssignment, IdentitySignal, SignalScore
from wellbeing.reasoning.alert_builder import AlertBuilder
from wellbeing.reasoning.explainer import Explainer, GroundingViolation, check_banned_phrases

T0 = datetime(2026, 3, 20, 14, 0, 0)


def _identity(confidence: float = 0.91) -> IdentityAssignment:
    return IdentityAssignment(
        subject_id="resident:ana",
        kind=SubjectKind.RESIDENT,
        confidence=confidence,
        signal_scores=(
            SignalScore(signal=IdentitySignal.BODY, score=0.93, weight=0.35),
            SignalScore(signal=IdentitySignal.GAIT, score=0.71, weight=0.20),
        ),
    )


def _fall_event() -> ActivityEvent:
    return ActivityEvent(
        event_id="evt_fall",
        subject_id="resident:ana",
        subject_kind=SubjectKind.RESIDENT,
        camera_id="cam-living",
        zone="living_room",
        label=ActivityLabel.FALL,
        window=TimeWindow(start=T0, end=T0 + timedelta(seconds=12)),
        confidence=0.86,
        identity_confidence=0.91,
        source=EventSource.POSE_RULE,
        evidence=("f101", "rapid_centroid_drop"),
    )


def _anomaly(metric: str = "active_minutes", sigma: float = -3.1) -> AnomalySignal:
    return AnomalySignal(
        anomaly_id="anom_1",
        subject_id="resident:ana",
        window=TimeWindow(start=T0, end=T0 + timedelta(hours=6)),
        metric=metric,
        bucket=Bucket.AFTERNOON,
        observed=18.0,
        baseline_median=64.0,
        deviation_sigma=sigma,
        score=0.82,
        method=AnomalyMethod.ZSCORE,
        severity=Severity.WARNING,
        evidence_event_ids=("evt_1", "evt_2"),
    )


def test_every_alert_answers_all_six_questions() -> None:
    explainer = Explainer(ReasoningConfig())
    explanation = explainer.for_anomaly(_anomaly(), AlertKind.ROUTINE_DEVIATION, _identity())
    assert explanation.is_complete
    assert len(explanation.as_lines()) == 6


def test_explanation_is_concrete_not_vague() -> None:
    """Rejects the 'unusual behavior detected' failure mode."""
    explainer = Explainer(ReasoningConfig())
    explanation = explainer.for_anomaly(_anomaly(), AlertKind.ROUTINE_DEVIATION, _identity())
    prose = explainer.render_prose(explanation)
    assert "46" in explanation.baseline_delta  # 64 - 18, the actual delta
    assert "64" in explanation.baseline_delta
    assert "unusual behavior" not in prose.lower()
    assert "minutes" in prose


def test_confidence_sentence_names_the_weakest_signal() -> None:
    explainer = Explainer(ReasoningConfig())
    explanation = explainer.for_anomaly(_anomaly(), AlertKind.ROUTINE_DEVIATION, _identity())
    assert "weakest signal was gait" in explanation.confidence


def test_banned_clinical_phrasing_is_blocked() -> None:
    config = ReasoningConfig()
    assert check_banned_phrases("The resident is depressed", config.banned_phrases)
    explainer = Explainer(config)
    bad = Explanation(
        what="The resident has dementia.",
        when="today",
        why_flagged="low activity",
        baseline_delta="below usual",
        confidence="high",
        check_next="check in",
    )
    with pytest.raises(GroundingViolation):
        explainer.render_prose(bad)


def test_generated_text_falls_back_to_the_deterministic_renderer() -> None:
    explainer = Explainer(ReasoningConfig())
    explanation = explainer.for_anomaly(_anomaly(), AlertKind.ROUTINE_DEVIATION, _identity())
    fallback = explainer.validate_generated("She has dementia and should take rest.", explanation)
    assert "dementia" not in fallback


def test_fall_alert_is_critical_and_requires_review() -> None:
    builder = AlertBuilder(AlertsConfig(), ReasoningConfig())
    assessment = FallAssessment(
        detected=True,
        confidence=0.88,
        rules_fired=("rapid_centroid_drop", "sustained_horizontal_torso", "post_event_stillness"),
        drop_ratio=0.52,
        drop_seconds=0.6,
        horizontal_hold_seconds=14.0,
        stillness_seconds=22.0,
        reason="centroid dropped 0.52 of body height in 0.6s",
    )
    alert = builder.from_fall(_fall_event(), assessment, _identity())
    assert alert.severity is Severity.CRITICAL
    assert alert.kind is AlertKind.FALL
    assert alert.requires_human_review
    assert alert.is_actionable
    assert "Go to the resident now" in alert.explanation.check_next


def test_low_identity_confidence_suppresses_behavioural_alerts() -> None:
    """Attributing behaviour to the wrong resident is worse than staying quiet."""
    builder = AlertBuilder(AlertsConfig(), ReasoningConfig())
    alert = builder.from_anomaly(_anomaly(), identity=_identity(confidence=0.31))
    assert not alert.is_actionable
    assert alert.suppressed_reason is not None
    assert "identity confidence" in alert.suppressed_reason


def test_sustained_deviation_is_reported_as_a_trend_not_a_daily_alert() -> None:
    builder = AlertBuilder(AlertsConfig(), ReasoningConfig())
    alert = builder.from_anomaly(_anomaly(), identity=_identity(), consecutive_days=9)
    assert alert.suppressed_reason is not None
    assert "trend" in alert.suppressed_reason


def test_daily_alert_cap_is_enforced_but_never_for_falls() -> None:
    builder = AlertBuilder(AlertsConfig(), ReasoningConfig())
    for _ in range(3):
        builder.from_anomaly(_anomaly(), identity=_identity())
    capped = builder.from_anomaly(_anomaly(), identity=_identity())
    assert capped.suppressed_reason == "daily alert cap for this resident already reached"

    assessment = FallAssessment(detected=True, confidence=0.9, rules_fired=("rapid_centroid_drop",))
    fall = builder.from_fall(_fall_event(), assessment, _identity())
    assert fall.is_actionable
