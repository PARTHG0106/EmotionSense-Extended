from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from wellbeing.config import AppConfig
from wellbeing.contracts.common import BBox, SubjectKind
from wellbeing.contracts.perception import (
    FrameQuality,
    IdentityAssignment,
    MotionState,
    PerceptionFrame,
    Posture,
    TrackObservation,
)

T0 = datetime(2026, 3, 2, 14, 0, 0)


@pytest.fixture
def config() -> AppConfig:
    """Packaged defaults. Tests must never depend on a site config being present."""
    return AppConfig()


def make_frame(
    index: int,
    posture: Posture,
    *,
    bbox: BBox | None = None,
    speed: float = 0.0,
    subject_id: str = "resident:ana",
    kind: SubjectKind = SubjectKind.RESIDENT,
    identity_confidence: float = 0.9,
    zone: str = "living_room",
    seconds: float = 1.0,
) -> PerceptionFrame:
    box = bbox or BBox(x1=100.0, y1=80.0, x2=180.0, y2=300.0)
    return PerceptionFrame(
        frame_id=f"f{index}",
        camera_id="cam-living",
        ts=T0 + timedelta(seconds=index * seconds),
        quality=FrameQuality(blur_score=80.0, luminance=120.0),
        tracks=(
            TrackObservation(
                track_id=1,
                bbox=box,
                posture=posture,
                posture_confidence=0.85,
                motion=MotionState(speed_px_s=speed),
                zone=zone,
                identity=IdentityAssignment(
                    subject_id=subject_id,
                    kind=kind,
                    confidence=identity_confidence,
                ),
            ),
        ),
        model_versions={"detector": "stub-detector-1"},
    )
