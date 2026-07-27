from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, EventSource
from wellbeing.contracts.alerts import Explanation
from wellbeing.contracts.behavior import Baseline, BaselineStatus, Bucket, DailyFeatures, DayType
from wellbeing.contracts.common import BBox, Severity, SubjectKind, TimeWindow

NOW = datetime(2026, 3, 2, 9, 0, 0)


def test_bbox_rejects_inverted_coordinates() -> None:
    with pytest.raises(ValidationError):
        BBox(x1=10.0, y1=10.0, x2=5.0, y2=20.0)


def test_time_window_rejects_reversed_interval() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=NOW, end=NOW - timedelta(seconds=1))


def test_activity_event_requires_evidence() -> None:
    """An event with no evidence cannot be explained, so it must not exist."""
    with pytest.raises(ValidationError):
        ActivityEvent(
            event_id="e1",
            subject_id="resident:ana",
            subject_kind=SubjectKind.RESIDENT,
            camera_id="cam-living",
            label=ActivityLabel.SITTING,
            window=TimeWindow(start=NOW, end=NOW + timedelta(minutes=5)),
            confidence=0.8,
            identity_confidence=0.9,
            source=EventSource.POSE_RULE,
            evidence=(),
        )


def test_contracts_are_immutable() -> None:
    window = TimeWindow(start=NOW, end=NOW + timedelta(minutes=1))
    with pytest.raises(ValidationError):
        window.start = NOW + timedelta(days=1)  # type: ignore[misc]


def test_zero_mad_baseline_does_not_produce_infinite_sigma() -> None:
    """A perfectly regular resident must not make every tiny change infinitely anomalous."""
    baseline = Baseline(
        subject_id="resident:ana",
        metric="active_minutes",
        bucket=Bucket.AFTERNOON,
        day_type=DayType.WEEKDAY,
        median=60.0,
        mad=0.0,
        n_days=14,
        status=BaselineStatus.STABLE,
        updated_at=NOW,
    )
    sigma = baseline.deviation_sigma(54.0)
    assert baseline.robust_sigma == pytest.approx(6.0)
    assert sigma == pytest.approx(-1.0)


def test_outage_day_is_excluded_from_baselines() -> None:
    """'No data' must never be treated as 'no activity'."""
    outage = DailyFeatures(
        subject_id="resident:ana",
        day=NOW.date(),
        bucket=Bucket.MORNING,
        features={"active_minutes": 0.0},
        completeness=0.2,
    )
    assert not outage.is_baseline_eligible(0.6)


def test_explanation_completeness_is_checked() -> None:
    incomplete = Explanation(
        what="x", when="y", why_flagged="z", baseline_delta="", confidence="c", check_next="n"
    )
    assert not incomplete.is_complete
    assert incomplete.missing_fields == ("baseline_delta",)


def test_severity_review_requirements() -> None:
    assert Severity.CRITICAL.requires_human_review
    assert Severity.WARNING.requires_human_review
    assert not Severity.ATTENTION.requires_human_review
    assert Severity.CRITICAL.rank > Severity.WARNING.rank
