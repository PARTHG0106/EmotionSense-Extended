from __future__ import annotations

from datetime import date, timedelta

import pytest

from tests.conftest import T0, make_frame
from wellbeing.config import AppConfig
from wellbeing.contracts.activity import ActivityLabel
from wellbeing.contracts.alerts import AlertKind
from wellbeing.contracts.behavior import Bucket, DailyFeatures
from wellbeing.contracts.common import BBox, Severity, SubjectKind
from wellbeing.contracts.perception import Posture
from wellbeing.pipeline import Pipeline

pytestmark = pytest.mark.integration

SUBJECT = "resident:ana"


def test_sitting_stream_becomes_one_event(config: AppConfig) -> None:
    frames = [make_frame(i, Posture.SITTING) for i in range(30)]
    pipeline = Pipeline(config)
    events, alerts = pipeline.process_frames(frames)
    assert len(events) == 1
    assert events[0].label is ActivityLabel.SITTING
    assert events[0].duration_seconds == pytest.approx(29.0)
    assert alerts == []


def test_label_flicker_shorter_than_min_duration_is_absorbed(config: AppConfig) -> None:
    """Single-frame flickers must never reach a caregiver."""
    frames = [make_frame(i, Posture.SITTING) for i in range(10)]
    frames.append(make_frame(10, Posture.STANDING))
    frames.extend(make_frame(i, Posture.SITTING) for i in range(11, 25))
    pipeline = Pipeline(config)
    events, _ = pipeline.process_frames(frames)
    labels = [e.label for e in events]
    assert ActivityLabel.STANDING_STILL not in labels


def test_fall_sequence_produces_one_critical_alert_with_full_explanation(
    config: AppConfig,
) -> None:
    upright = BBox(x1=100.0, y1=80.0, x2=180.0, y2=300.0)
    floor = BBox(x1=100.0, y1=250.0, x2=320.0, y2=330.0)
    frames = [make_frame(i, Posture.STANDING, bbox=upright, speed=25.0) for i in range(4)]
    frames.extend(
        make_frame(i, Posture.LYING, bbox=floor, speed=1.0, seconds=1.0) for i in range(5, 30)
    )
    pipeline = Pipeline(config)
    _, alerts = pipeline.process_frames(frames)

    critical = [a for a in alerts if a.severity is Severity.CRITICAL]
    assert len(critical) == 1
    alert = critical[0]
    assert alert.kind is AlertKind.FALL
    assert alert.requires_human_review
    assert alert.explanation.is_complete
    assert alert.prose and "living room" in alert.prose


def test_visitor_activity_does_not_enter_resident_features(config: AppConfig) -> None:
    frames = [
        make_frame(i, Posture.WALKING if False else Posture.STANDING, speed=30.0,
                   subject_id="visitor:abc", kind=SubjectKind.VISITOR)
        for i in range(20)
    ]
    pipeline = Pipeline(config)
    pipeline.process_frames(frames)
    review = pipeline.review_day("visitor:abc", T0.date())
    afternoon = next(f for f in review.features if f.bucket is Bucket.AFTERNOON)
    assert afternoon.features["active_minutes"] == 0.0
    assert afternoon.features["visitor_minutes"] > 0.0


def test_no_anomaly_alerts_during_baseline_warmup(config: AppConfig) -> None:
    """Cold start must be silent, not noisy."""
    frames = [make_frame(i, Posture.LYING) for i in range(60)]
    pipeline = Pipeline(config)
    pipeline.process_frames(frames)
    review = pipeline.review_day(SUBJECT, T0.date(), history=[])
    assert review.anomalies == []
    assert review.actionable_alerts == []


def test_quiet_afternoon_against_an_established_baseline_alerts(config: AppConfig) -> None:
    history = [
        DailyFeatures(
            subject_id=SUBJECT,
            day=date(2026, 2, 1) + timedelta(days=i),
            bucket=Bucket.AFTERNOON,
            features={
                "active_minutes": 60.0 + (i % 3),
                "walking_minutes": 20.0,
                "walking_bouts": 8.0,
                "sit_to_stand_transitions": 12.0,
                "longest_inactive_minutes": 30.0,
                "lying_minutes": 20.0,
                "meal_events": 1.0,
                "zone_changes": 10.0,
                "visitor_minutes": 0.0,
            },
            completeness=1.0,
        )
        for i in range(20)
    ]
    frames = [make_frame(i, Posture.LYING) for i in range(120)]
    pipeline = Pipeline(config)
    pipeline.process_frames(frames)
    review = pipeline.review_day(SUBJECT, T0.date(), history=history)

    assert review.anomalies, "a near-zero activity afternoon must deviate from a 60-minute baseline"
    assert all(a.explanation.is_complete for a in review.alerts)
    assert len(review.alerts) <= config.behavior.anomaly.max_alerts_per_resident_per_day
