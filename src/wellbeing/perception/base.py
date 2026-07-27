"""Adapter protocols for the perception layer.

Every model is behind a ``Protocol`` so that a real backend (Ultralytics, RTMPose,
FastReID) and a deterministic stub are interchangeable through configuration alone.
This is what lets the full pipeline, the API and the test suite run with no GPU and no
downloaded weights.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import numpy as np

from wellbeing.contracts.common import BBox, Keypoint

#: Frames are plain arrays. Nothing above L1 ever receives one of these.
Frame = np.ndarray[Any, Any]


@dataclass(frozen=True, slots=True)
class Detection:
    """A single person detection before tracking."""

    bbox: BBox
    confidence: float
    label: str = "person"


@dataclass(slots=True)
class TrackState:
    """Mutable per-track state owned by the tracker."""

    track_id: int
    bbox: BBox
    confidence: float
    age_frames: int = 0
    hits: int = 1
    last_seen: datetime | None = None
    history: list[tuple[datetime, tuple[float, float]]] = field(default_factory=list)

    @property
    def is_confirmed(self) -> bool:
        return self.hits >= 3


@runtime_checkable
class Detector(Protocol):
    """Person detector."""

    @property
    def version(self) -> str: ...

    def detect(self, frame: Frame) -> list[Detection]: ...


@runtime_checkable
class Tracker(Protocol):
    """Multi-object tracker producing stable short-term track ids."""

    @property
    def version(self) -> str: ...

    def update(self, detections: list[Detection], ts: datetime) -> list[TrackState]: ...


@runtime_checkable
class PoseEstimator(Protocol):
    """Top-down pose estimator."""

    @property
    def version(self) -> str: ...

    def estimate(self, frame: Frame, bbox: BBox) -> tuple[Keypoint, ...]: ...


@runtime_checkable
class ReIDEncoder(Protocol):
    """Appearance / gait / face embedding extractor.

    Implementations must return L2-normalised vectors so that similarity is a plain
    inner product and thresholds stay comparable across backends.
    """

    @property
    def version(self) -> str: ...

    @property
    def embedding_dim(self) -> int: ...

    def encode(self, frame: Frame, bbox: BBox) -> np.ndarray[Any, Any]: ...


def l2_normalise(vector: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Return the unit-norm version of ``vector``; a zero vector is returned unchanged."""
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector.astype(np.float32)
    return (vector / norm).astype(np.float32)
