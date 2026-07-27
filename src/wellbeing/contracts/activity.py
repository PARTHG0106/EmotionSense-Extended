"""L2 activity contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from wellbeing.contracts.common import Confidence, Contract, SubjectKind, TimeWindow


class ActivityLabel(StrEnum):
    WALKING = "walking"
    STANDING_STILL = "standing_still"
    SITTING = "sitting"
    RESTING = "resting"
    LYING = "lying"
    TRANSFER = "transfer"
    MEAL = "meal"
    DRINK = "drink"
    MEDICATION_ROUTINE = "medication_routine"
    GROOMING = "grooming"
    ROOM_ENTRY = "room_entry"
    ROOM_EXIT = "room_exit"
    PROLONGED_INACTIVITY = "prolonged_inactivity"
    UNSAFE_POSTURE = "unsafe_posture"
    FALL = "fall"
    UNKNOWN = "unknown"

    @property
    def is_ambulatory(self) -> bool:
        return self in (ActivityLabel.WALKING, ActivityLabel.TRANSFER)

    @property
    def is_safety_critical(self) -> bool:
        return self in (ActivityLabel.FALL, ActivityLabel.PROLONGED_INACTIVITY)


class EventSource(StrEnum):
    """How an event was produced. Kept for auditability of every alert."""

    POSE_RULE = "pose_rule"
    VIDEO_MODEL = "video_model"
    FUSION = "fusion"
    SENSOR = "sensor"


class ActivityEvent(Contract):
    """A closed, timestamped activity interval for one subject.

    ``evidence`` is mandatory. An event that cannot name the frames or rules behind it
    cannot be explained to a caregiver, and an unexplainable alert is worse than none.
    """

    event_id: str
    subject_id: str
    subject_kind: SubjectKind
    camera_id: str
    zone: str | None = None
    label: ActivityLabel
    window: TimeWindow
    confidence: Confidence
    identity_confidence: Confidence
    source: EventSource
    evidence: tuple[str, ...]
    attributes: dict[str, float] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_evidence(self) -> ActivityEvent:
        if not self.evidence:
            raise ValueError("activity events must carry at least one evidence reference")
        return self

    @property
    def duration_seconds(self) -> float:
        return self.window.duration_seconds

    @property
    def duration_minutes(self) -> float:
        return self.window.duration_minutes


class FallAssessment(Contract):
    """Result of the rule-first fall detector.

    The fired rule ids are the explanation. A learned score may raise confidence but
    never replaces the kinematic evidence, because that is what bounds behaviour on
    footage no model has seen.
    """

    detected: bool
    confidence: Confidence
    rules_fired: tuple[str, ...] = ()
    drop_ratio: float = 0.0
    drop_seconds: float = 0.0
    horizontal_hold_seconds: float = 0.0
    stillness_seconds: float = 0.0
    model_confidence: Confidence | None = None
    reason: str = ""
    self_recovered: bool = False
