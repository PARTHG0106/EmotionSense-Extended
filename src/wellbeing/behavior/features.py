"""Daily behaviour features derived from the activity event stream.

These metrics are chosen because a caregiver can act on each one, and because each maps
to a sentence in a report. Metrics that cannot be explained in one clause are not worth
collecting.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime

from wellbeing.config import BaselineConfig
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel
from wellbeing.contracts.behavior import Bucket, DailyFeatures
from wellbeing.contracts.common import SubjectKind

#: Canonical metric names. Baselines, anomalies and report copy all key off these.
FEATURE_METRICS: tuple[str, ...] = (
    "active_minutes",
    "walking_minutes",
    "walking_bouts",
    "sit_to_stand_transitions",
    "longest_inactive_minutes",
    "lying_minutes",
    "meal_events",
    "zone_changes",
    "visitor_minutes",
)

_ACTIVE_LABELS = (
    ActivityLabel.WALKING,
    ActivityLabel.TRANSFER,
    ActivityLabel.STANDING_STILL,
    ActivityLabel.MEAL,
    ActivityLabel.GROOMING,
)


def bucket_of(moment: datetime, config: BaselineConfig) -> Bucket:
    """Map a timestamp onto its configured time-of-day bucket."""
    hour = moment.hour
    for name, (start, end) in config.bucket_hours.items():
        if start <= hour < end:
            return Bucket(name)
    return Bucket.NIGHT


def _transitions(events: Sequence[ActivityEvent]) -> int:
    """Count sit/lie -> stand transitions, the most useful single mobility proxy.

    Sit-to-stand count correlates with lower-limb strength and is one of the earliest
    quantities to fall when an older adult declines.
    """
    count = 0
    ordered = sorted(events, key=lambda e: e.window.start)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        was_low = previous.label in (ActivityLabel.SITTING, ActivityLabel.LYING)
        now_up = current.label in (ActivityLabel.STANDING_STILL, ActivityLabel.WALKING)
        if was_low and now_up:
            count += 1
    return count


def _longest_inactive_minutes(events: Sequence[ActivityEvent]) -> float:
    inactive = [
        e
        for e in events
        if e.label in (ActivityLabel.SITTING, ActivityLabel.LYING, ActivityLabel.RESTING)
    ]
    return max((e.duration_minutes for e in inactive), default=0.0)


def compute_daily_features(
    events: Iterable[ActivityEvent],
    subject_id: str,
    day: date,
    bucket: Bucket,
    config: BaselineConfig,
    completeness: float = 1.0,
) -> DailyFeatures:
    """Aggregate one subject's events for one day and bucket.

    ``completeness`` must be supplied by the caller from camera health, and is the guard
    that stops an outage being recorded as a day of zero activity.
    """
    selected = [
        e
        for e in events
        if e.subject_id == subject_id
        and e.window.start.date() == day
        and bucket_of(e.window.start, config) is bucket
    ]
    resident_events = [e for e in selected if e.subject_kind is SubjectKind.RESIDENT]
    visitor_events = [e for e in selected if e.subject_kind is SubjectKind.VISITOR]

    walking = [e for e in resident_events if e.label is ActivityLabel.WALKING]
    features: dict[str, float] = {
        "active_minutes": sum(
            e.duration_minutes for e in resident_events if e.label in _ACTIVE_LABELS
        ),
        "walking_minutes": sum(e.duration_minutes for e in walking),
        "walking_bouts": float(len(walking)),
        "sit_to_stand_transitions": float(_transitions(resident_events)),
        "longest_inactive_minutes": _longest_inactive_minutes(resident_events),
        "lying_minutes": sum(
            e.duration_minutes for e in resident_events if e.label is ActivityLabel.LYING
        ),
        "meal_events": float(
            sum(1 for e in resident_events if e.label is ActivityLabel.MEAL)
        ),
        "zone_changes": float(_zone_changes(resident_events)),
        "visitor_minutes": sum(e.duration_minutes for e in visitor_events),
    }
    return DailyFeatures(
        subject_id=subject_id,
        day=day,
        bucket=bucket,
        features=features,
        completeness=max(0.0, min(1.0, completeness)),
    )


def _zone_changes(events: Sequence[ActivityEvent]) -> int:
    ordered = sorted((e for e in events if e.zone), key=lambda e: e.window.start)
    return sum(
        1
        for previous, current in zip(ordered, ordered[1:], strict=False)
        if previous.zone != current.zone
    )


def metric_units() -> Mapping[str, str]:
    """Human units used verbatim in explanations, so prose never invents them."""
    return {
        "active_minutes": "minutes of activity",
        "walking_minutes": "minutes of walking",
        "walking_bouts": "walking bouts",
        "sit_to_stand_transitions": "sit-to-stand transitions",
        "longest_inactive_minutes": "minutes in the longest inactive stretch",
        "lying_minutes": "minutes lying down",
        "meal_events": "meals observed",
        "zone_changes": "room changes",
        "visitor_minutes": "minutes with a visitor present",
    }
