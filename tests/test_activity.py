from __future__ import annotations

from datetime import datetime, timedelta

from wellbeing.activity.fall import FallDetector, FallSample
from wellbeing.activity.posture import classify_posture, torso_angle_deg
from wellbeing.config import ActivityConfig, PostureRulesConfig
from wellbeing.contracts.common import BBox
from wellbeing.contracts.perception import Posture
from wellbeing.perception.stubs import StubPoseEstimator

T0 = datetime(2026, 3, 2, 15, 0, 0)
UPRIGHT = BBox(x1=100.0, y1=80.0, x2=180.0, y2=300.0)
HORIZONTAL = BBox(x1=100.0, y1=250.0, x2=320.0, y2=330.0)


def _keypoints(bbox: BBox):
    return StubPoseEstimator().estimate(None, bbox)  # type: ignore[arg-type]


def test_upright_skeleton_is_standing() -> None:
    posture, confidence = classify_posture(
        _keypoints(UPRIGHT), UPRIGHT, PostureRulesConfig()
    )
    assert posture is Posture.STANDING
    assert confidence > 0.7


def test_horizontal_skeleton_is_lying() -> None:
    angle = torso_angle_deg(_keypoints(HORIZONTAL))
    assert angle is not None and angle > 55.0
    posture, confidence = classify_posture(
        _keypoints(HORIZONTAL), HORIZONTAL, PostureRulesConfig()
    )
    assert posture is Posture.LYING
    assert confidence >= 0.9


def test_missing_keypoints_fall_back_to_geometry_with_lower_confidence() -> None:
    posture, confidence = classify_posture((), HORIZONTAL, PostureRulesConfig())
    assert posture is Posture.LYING
    assert confidence < 0.7


def _fall_sequence(fall: bool, recover: bool = False) -> list[FallSample]:
    samples: list[FallSample] = []
    # Standing.
    for i in range(5):
        samples.append(
            FallSample(
                ts=T0 + timedelta(seconds=i * 0.2),
                centroid_y=100.0,
                body_height=200.0,
                torso_angle_deg=5.0,
                posture=Posture.STANDING,
                speed_px_s=20.0,
            )
        )
    drop = 180.0 if fall else 110.0
    samples.append(
        FallSample(
            ts=T0 + timedelta(seconds=1.2),
            centroid_y=drop,
            body_height=200.0,
            torso_angle_deg=80.0,
            posture=Posture.LYING,
            speed_px_s=4.0,
        )
    )
    for i in range(1, 25):
        samples.append(
            FallSample(
                ts=T0 + timedelta(seconds=1.2 + i),
                centroid_y=drop,
                body_height=200.0,
                torso_angle_deg=80.0,
                posture=Posture.LYING,
                speed_px_s=1.0,
            )
        )
    if recover:
        samples.append(
            FallSample(
                ts=T0 + timedelta(seconds=30.0),
                centroid_y=100.0,
                body_height=200.0,
                torso_angle_deg=5.0,
                posture=Posture.STANDING,
                speed_px_s=25.0,
            )
        )
    return samples


def test_fall_signature_is_detected_with_named_rules() -> None:
    detector = FallDetector(ActivityConfig().fall)
    assessment = detector.ingest(_fall_sequence(fall=True))
    assert assessment.detected
    assert "rapid_centroid_drop" in assessment.rules_fired
    assert "sustained_horizontal_torso" in assessment.rules_fired
    assert assessment.confidence >= 0.7
    assert "centroid dropped" in assessment.reason


def test_slow_controlled_lie_down_is_not_a_fall() -> None:
    """Lying down on a sofa lacks the rapid drop signature."""
    detector = FallDetector(ActivityConfig().fall)
    assessment = detector.ingest(_fall_sequence(fall=False))
    assert not assessment.detected


def test_self_recovery_suppresses_the_alert() -> None:
    """Getting back up unaided is a voluntary transfer, not a fall to escalate."""
    detector = FallDetector(ActivityConfig().fall)
    assessment = detector.ingest(_fall_sequence(fall=True, recover=True))
    assert not assessment.detected
    assert assessment.self_recovered
