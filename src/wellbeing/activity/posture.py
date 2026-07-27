"""Geometric posture classification from COCO-17 keypoints.

Pose geometry rather than a learned classifier, for three reasons: it is explainable to a
caregiver, it needs no training data from the deployment site, and it degrades predictably
when keypoints are missing. A learned model refines these labels; it does not replace them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from wellbeing.config import PostureRulesConfig
from wellbeing.contracts.common import BBox, Keypoint
from wellbeing.contracts.perception import Posture


def _mid(points: Sequence[Keypoint], left: str, right: str, min_conf: float) -> tuple[float, float] | None:
    index = {p.name: p for p in points}
    a, b = index.get(left), index.get(right)
    usable = [p for p in (a, b) if p is not None and p.confidence >= min_conf]
    if not usable:
        return None
    return (
        sum(p.x for p in usable) / len(usable),
        sum(p.y for p in usable) / len(usable),
    )


def torso_angle_deg(keypoints: Sequence[Keypoint], min_conf: float = 0.3) -> float | None:
    """Angle of the shoulder-to-hip axis from vertical, in degrees.

    ``0`` is fully upright, ``90`` is fully horizontal. Returns ``None`` when the torso
    keypoints are not reliable enough to make a claim.
    """
    shoulders = _mid(keypoints, "left_shoulder", "right_shoulder", min_conf)
    hips = _mid(keypoints, "left_hip", "right_hip", min_conf)
    if shoulders is None or hips is None:
        return None
    dx = hips[0] - shoulders[0]
    dy = hips[1] - shoulders[1]
    if dx == 0.0 and dy == 0.0:
        return None
    return abs(math.degrees(math.atan2(abs(dx), abs(dy))))


def _hip_knee_ratio(keypoints: Sequence[Keypoint], min_conf: float) -> float | None:
    """Vertical hip-to-knee separation as a fraction of shoulder-to-knee separation.

    Sitting compresses this ratio: the hips drop close to knee height.
    """
    shoulders = _mid(keypoints, "left_shoulder", "right_shoulder", min_conf)
    hips = _mid(keypoints, "left_hip", "right_hip", min_conf)
    knees = _mid(keypoints, "left_knee", "right_knee", min_conf)
    if shoulders is None or hips is None or knees is None:
        return None
    span = abs(knees[1] - shoulders[1])
    if span <= 1e-6:
        return None
    return abs(knees[1] - hips[1]) / span


def classify_posture(
    keypoints: Sequence[Keypoint],
    bbox: BBox,
    config: PostureRulesConfig,
    min_keypoint_conf: float = 0.3,
) -> tuple[Posture, float]:
    """Return ``(posture, confidence)``.

    Falls back to bounding-box aspect ratio when the skeleton is unusable, which is the
    common case in low-resolution or heavily occluded footage. Confidence is reported
    lower in that path so downstream layers can discount it rather than trust it blindly.
    """
    angle = torso_angle_deg(keypoints, min_keypoint_conf)

    if angle is None:
        # Geometry-only fallback: a wider-than-tall person box is a lying prior.
        if bbox.aspect_ratio > 1.15:
            return Posture.LYING, 0.55
        if bbox.aspect_ratio < 0.45:
            return Posture.STANDING, 0.50
        return Posture.UNKNOWN, 0.20

    if angle >= config.lying_torso_angle_deg:
        # Strong agreement between skeleton and box geometry raises confidence.
        confidence = 0.90 if bbox.aspect_ratio > 1.0 else 0.72
        return Posture.LYING, confidence

    ratio = _hip_knee_ratio(keypoints, min_keypoint_conf)
    if ratio is not None and ratio <= config.sitting_hip_knee_ratio:
        if ratio <= config.sitting_hip_knee_ratio * 0.5:
            return Posture.CROUCHING, 0.65
        return Posture.SITTING, 0.80
    return Posture.STANDING, 0.85
