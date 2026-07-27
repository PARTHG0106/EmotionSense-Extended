"""Turns per-frame perception into closed, minimum-duration activity events.

No alert is ever raised from a single frame. Short label flickers are absorbed here, which
is the cheapest false-alarm reduction available in the whole system.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

from wellbeing.config import ActivityConfig
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, EventSource
from wellbeing.contracts.common import SubjectKind, TimeWindow
from wellbeing.contracts.perception import PerceptionFrame, Posture

_POSTURE_TO_LABEL: dict[Posture, ActivityLabel] = {
    Posture.STANDING: ActivityLabel.STANDING_STILL,
    Posture.SITTING: ActivityLabel.SITTING,
    Posture.LYING: ActivityLabel.LYING,
    Posture.CROUCHING: ActivityLabel.UNSAFE_POSTURE,
    Posture.UNKNOWN: ActivityLabel.UNKNOWN,
}


@dataclass(slots=True)
class PostureSample:
    """Flattened per-frame view used while accumulating an event."""

    ts: datetime
    frame_id: str
    camera_id: str
    subject_id: str
    subject_kind: SubjectKind
    identity_confidence: float
    label: ActivityLabel
    label_confidence: float
    zone: str | None


@dataclass(slots=True)
class _OpenEvent:
    label: ActivityLabel
    start: datetime
    end: datetime
    camera_id: str
    zone: str | None
    subject_id: str
    subject_kind: SubjectKind
    confidences: list[float]
    identity_confidences: list[float]
    evidence: list[str]


class EventAssembler:
    """Accumulates samples per subject and emits events on label change."""

    def __init__(self, config: ActivityConfig, model_versions: dict[str, str] | None = None) -> None:
        self._config = config
        self._open: dict[str, _OpenEvent] = {}
        self._model_versions = model_versions or {}

    @staticmethod
    def samples_from_frame(frame: PerceptionFrame) -> Iterator[PostureSample]:
        for track in frame.tracks:
            label = _POSTURE_TO_LABEL.get(track.posture, ActivityLabel.UNKNOWN)
            if track.posture is Posture.STANDING and not track.motion.is_still(8.0):
                label = ActivityLabel.WALKING
            yield PostureSample(
                ts=frame.ts,
                frame_id=frame.frame_id,
                camera_id=frame.camera_id,
                subject_id=track.identity.subject_id,
                subject_kind=track.identity.kind,
                identity_confidence=track.identity.confidence,
                label=label,
                label_confidence=track.posture_confidence,
                zone=track.zone,
            )

    def push(self, sample: PostureSample) -> ActivityEvent | None:
        """Add a sample; returns a completed event when the label or zone changes."""
        current = self._open.get(sample.subject_id)
        if current is None:
            self._open[sample.subject_id] = self._start(sample)
            return None
        if current.label is sample.label and current.zone == sample.zone:
            current.end = sample.ts
            current.confidences.append(sample.label_confidence)
            current.identity_confidences.append(sample.identity_confidence)
            if len(current.evidence) < 32:
                current.evidence.append(sample.frame_id)
            return None
        completed = self._close(current)
        self._open[sample.subject_id] = self._start(sample)
        return completed

    def flush(self) -> list[ActivityEvent]:
        """Close every open event, e.g. at end of stream or shutdown."""
        events = [event for event in (self._close(o) for o in self._open.values()) if event]
        self._open.clear()
        return events

    def process(self, frames: Iterable[PerceptionFrame]) -> list[ActivityEvent]:
        events: list[ActivityEvent] = []
        for frame in frames:
            for sample in self.samples_from_frame(frame):
                event = self.push(sample)
                if event is not None:
                    events.append(event)
        events.extend(self.flush())
        return events

    # ---------------------------------------------------------------- internals
    def _start(self, sample: PostureSample) -> _OpenEvent:
        return _OpenEvent(
            label=sample.label,
            start=sample.ts,
            end=sample.ts,
            camera_id=sample.camera_id,
            zone=sample.zone,
            subject_id=sample.subject_id,
            subject_kind=sample.subject_kind,
            confidences=[sample.label_confidence],
            identity_confidences=[sample.identity_confidence],
            evidence=[sample.frame_id],
        )

    def _close(self, open_event: _OpenEvent) -> ActivityEvent | None:
        window = TimeWindow(start=open_event.start, end=open_event.end)
        if window.duration_seconds < self._config.min_event_duration_seconds:
            return None
        if open_event.label is ActivityLabel.UNKNOWN:
            return None
        mean_conf = sum(open_event.confidences) / len(open_event.confidences)
        mean_identity = sum(open_event.identity_confidences) / len(open_event.identity_confidences)
        return ActivityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            subject_id=open_event.subject_id,
            subject_kind=open_event.subject_kind,
            camera_id=open_event.camera_id,
            zone=open_event.zone,
            label=open_event.label,
            window=window,
            confidence=min(1.0, max(0.0, mean_conf)),
            identity_confidence=min(1.0, max(0.0, mean_identity)),
            source=EventSource.POSE_RULE,
            evidence=tuple(open_event.evidence),
            model_versions=dict(self._model_versions),
        )
