"""Typed contracts exchanged between layers. Single source of truth."""

from wellbeing.contracts.activity import (
    ActivityEvent,
    ActivityLabel,
    EventSource,
    FallAssessment,
)
from wellbeing.contracts.alerts import Alert, AlertKind, Explanation
from wellbeing.contracts.behavior import (
    AnomalyMethod,
    AnomalySignal,
    Baseline,
    BaselineStatus,
    BehaviorProfile,
    Bucket,
    DailyFeatures,
    DayType,
    RiskLevel,
    TrendDirection,
    TrendResult,
)
from wellbeing.contracts.common import BBox, Keypoint, Severity, SubjectKind, TimeWindow
from wellbeing.contracts.perception import (
    FrameQuality,
    IdentityAssignment,
    IdentitySignal,
    MotionState,
    PerceptionFrame,
    Posture,
    SignalScore,
    TrackObservation,
)

__all__ = [
    "ActivityEvent",
    "ActivityLabel",
    "Alert",
    "AlertKind",
    "AnomalyMethod",
    "AnomalySignal",
    "BBox",
    "Baseline",
    "BaselineStatus",
    "BehaviorProfile",
    "Bucket",
    "DailyFeatures",
    "DayType",
    "EventSource",
    "Explanation",
    "FallAssessment",
    "FrameQuality",
    "IdentityAssignment",
    "IdentitySignal",
    "Keypoint",
    "MotionState",
    "PerceptionFrame",
    "Posture",
    "RiskLevel",
    "Severity",
    "SignalScore",
    "SubjectKind",
    "TimeWindow",
    "TrackObservation",
    "TrendDirection",
    "TrendResult",
]
