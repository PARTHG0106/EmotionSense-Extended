"""Deterministic stub adapters.

These are not placeholders for missing work: they are the reference implementations that
keep the pipeline runnable and testable without GPUs or weights, and they define the
exact behaviour a real backend must reproduce.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

import numpy as np

from wellbeing.contracts.common import BBox, Keypoint
from wellbeing.perception.base import Detection, Frame, TrackState, l2_normalise

COCO_KEYPOINTS: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)


def _seed_from(*parts: object) -> int:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


class StubDetector:
    """Emits one stable detection per configured subject region."""

    version = "stub-detector-1"

    def __init__(self, boxes: list[BBox] | None = None, confidence: float = 0.9) -> None:
        self._boxes = boxes or [BBox(x1=100.0, y1=80.0, x2=180.0, y2=300.0)]
        self._confidence = confidence

    def detect(self, frame: Frame) -> list[Detection]:  # noqa: ARG002 - frame unused by design
        return [Detection(bbox=b, confidence=self._confidence) for b in self._boxes]


class StubTracker:
    """Greedy IoU tracker. Small, but real enough to exercise id continuity logic."""

    version = "stub-tracker-1"

    def __init__(self, iou_threshold: float = 0.3, max_age_frames: int = 60) -> None:
        self._iou_threshold = iou_threshold
        self._max_age = max_age_frames
        self._tracks: dict[int, TrackState] = {}
        self._next_id = 1

    @staticmethod
    def _iou(a: BBox, b: BBox) -> float:
        ix1, iy1 = max(a.x1, b.x1), max(a.y1, b.y1)
        ix2, iy2 = min(a.x2, b.x2), min(a.y2, b.y2)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        inter = (ix2 - ix1) * (iy2 - iy1)
        union = a.width * a.height + b.width * b.height - inter
        return inter / union if union > 0 else 0.0

    def update(self, detections: list[Detection], ts: datetime) -> list[TrackState]:
        unmatched = list(detections)
        for track in self._tracks.values():
            track.age_frames += 1
        for track in sorted(self._tracks.values(), key=lambda t: -t.hits):
            best = max(unmatched, key=lambda d: self._iou(track.bbox, d.bbox), default=None)
            if best is None or self._iou(track.bbox, best.bbox) < self._iou_threshold:
                continue
            track.bbox = best.bbox
            track.confidence = best.confidence
            track.hits += 1
            track.age_frames = 0
            track.last_seen = ts
            track.history.append((ts, best.bbox.center))
            unmatched.remove(best)
        for detection in unmatched:
            track = TrackState(
                track_id=self._next_id,
                bbox=detection.bbox,
                confidence=detection.confidence,
                last_seen=ts,
                history=[(ts, detection.bbox.center)],
            )
            self._tracks[self._next_id] = track
            self._next_id += 1
        self._tracks = {
            tid: t for tid, t in self._tracks.items() if t.age_frames <= self._max_age
        }
        return [t for t in self._tracks.values() if t.age_frames == 0]


class StubPoseEstimator:
    """Generates an anatomically plausible upright skeleton inside the given box.

    Keypoints are placed from box geometry, so a wide box yields a horizontal torso and
    the posture classifier reports ``lying`` - the behaviour a real estimator would show.
    """

    version = "stub-pose-1"

    def estimate(self, frame: Frame, bbox: BBox) -> tuple[Keypoint, ...]:  # noqa: ARG002
        w, h = bbox.width, bbox.height
        lying = bbox.aspect_ratio > 1.0
        # Fractional layout along the dominant body axis.
        layout: dict[str, tuple[float, float]] = {
            "nose": (0.50, 0.06),
            "left_eye": (0.46, 0.05),
            "right_eye": (0.54, 0.05),
            "left_ear": (0.42, 0.06),
            "right_ear": (0.58, 0.06),
            "left_shoulder": (0.38, 0.20),
            "right_shoulder": (0.62, 0.20),
            "left_elbow": (0.32, 0.35),
            "right_elbow": (0.68, 0.35),
            "left_wrist": (0.30, 0.48),
            "right_wrist": (0.70, 0.48),
            "left_hip": (0.42, 0.55),
            "right_hip": (0.58, 0.55),
            "left_knee": (0.42, 0.76),
            "right_knee": (0.58, 0.76),
            "left_ankle": (0.42, 0.96),
            "right_ankle": (0.58, 0.96),
        }
        points: list[Keypoint] = []
        for name in COCO_KEYPOINTS:
            across, along = layout[name]
            if lying:
                # Rotate the layout: the body axis runs horizontally.
                x = bbox.x1 + along * w
                y = bbox.y1 + across * h
            else:
                x = bbox.x1 + across * w
                y = bbox.y1 + along * h
            points.append(Keypoint(name=name, x=x, y=y, confidence=0.9))
        return tuple(points)


class StubReIDEncoder:
    """Content-addressed embeddings.

    The vector depends only on the quantised box geometry, so the same person in the same
    place yields the same embedding: deterministic, and enough to test gallery matching,
    thresholds and the unknown path.
    """

    version = "stub-reid-1"

    def __init__(self, embedding_dim: int = 512, salt: str = "body") -> None:
        self._dim = embedding_dim
        self._salt = salt

    @property
    def embedding_dim(self) -> int:
        return self._dim

    def encode(self, frame: Frame, bbox: BBox) -> np.ndarray[Any, Any]:  # noqa: ARG002
        seed = _seed_from(self._salt, round(bbox.x1 / 32), round(bbox.y1 / 32))
        rng = np.random.default_rng(seed)
        return l2_normalise(rng.normal(size=self._dim).astype(np.float32))

    def encode_identity(self, subject_id: str) -> np.ndarray[Any, Any]:
        """Deterministic enrollment vector for a known subject, used by tests and demos."""
        rng = np.random.default_rng(_seed_from(self._salt, subject_id))
        return l2_normalise(rng.normal(size=self._dim).astype(np.float32))
