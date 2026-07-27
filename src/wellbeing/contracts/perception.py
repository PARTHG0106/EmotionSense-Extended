"""L1 perception contracts: what the pixel-facing layer is allowed to publish."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from wellbeing.contracts.common import BBox, Confidence, Contract, Keypoint, SubjectKind


class Posture(StrEnum):
    STANDING = "standing"
    SITTING = "sitting"
    LYING = "lying"
    CROUCHING = "crouching"
    UNKNOWN = "unknown"


class IdentitySignal(StrEnum):
    """Independent identity evidence sources.

    Each degrades under different conditions, which is the entire reason the resolver
    fuses them rather than trusting appearance alone.
    """

    BODY = "body"
    FACE = "face"
    GAIT = "gait"
    ANTHROPOMETRY = "anthropometry"
    SPATIOTEMPORAL_PRIOR = "spatiotemporal_prior"


class FrameQuality(Contract):
    """Per-frame conditions. Poor quality discounts confidence rather than being ignored."""

    blur_score: float = Field(ge=0.0, description="variance of Laplacian; higher is sharper")
    luminance: float = Field(ge=0.0, le=255.0)
    occlusion_ratio: float = Field(ge=0.0, le=1.0, default=0.0)

    def is_usable(self, min_blur_score: float) -> bool:
        return self.blur_score >= min_blur_score and 12.0 <= self.luminance <= 250.0


class CropQuality(Contract):
    """Quality of a person crop. Gates whether a crop may update the identity gallery."""

    blur_score: float = Field(ge=0.0)
    height_px: float = Field(gt=0.0)
    truncation: float = Field(ge=0.0, le=1.0, default=0.0)

    def is_gallery_eligible(
        self, min_blur_score: float, min_height_px: float, max_truncation: float
    ) -> bool:
        """A low-quality crop must never be written into the gallery.

        Gallery poisoning is the most common cause of slow identity collapse: one blurred
        half-occluded crop enrolled as a prototype degrades every later match.
        """
        return (
            self.blur_score >= min_blur_score
            and self.height_px >= min_height_px
            and self.truncation <= max_truncation
        )


class MotionState(Contract):
    speed_px_s: float = Field(ge=0.0)
    direction_deg: float | None = None
    stillness_seconds: float = Field(ge=0.0, default=0.0)

    def is_still(self, speed_threshold_px_s: float) -> bool:
        return self.speed_px_s <= speed_threshold_px_s


class SignalScore(Contract):
    """One identity signal's contribution, kept so any assignment can be explained."""

    signal: IdentitySignal
    score: Confidence
    weight: float = Field(ge=0.0, le=1.0)

    @property
    def contribution(self) -> float:
        return self.score * self.weight


class IdentityAssignment(Contract):
    """Fused identity for a track.

    ``confidence`` is fused over the whole track, never a single frame.
    """

    subject_id: str
    kind: SubjectKind
    confidence: Confidence
    signal_scores: tuple[SignalScore, ...] = ()
    frames_of_agreement: int = Field(ge=0, default=0)

    @property
    def signals_used(self) -> tuple[IdentitySignal, ...]:
        return tuple(s.signal for s in self.signal_scores)

    @property
    def weakest_signal(self) -> IdentitySignal | None:
        """Named in explanations so caregivers see *why* confidence is what it is."""
        if not self.signal_scores:
            return None
        return min(self.signal_scores, key=lambda s: s.score).signal

    def supports_behavior_claims(self, floor: float) -> bool:
        """Behavioural claims require a known subject above the configured floor."""
        return self.kind is SubjectKind.RESIDENT and self.confidence >= floor


class TrackObservation(Contract):
    track_id: int
    bbox: BBox
    keypoints: tuple[Keypoint, ...] = ()
    posture: Posture = Posture.UNKNOWN
    posture_confidence: Confidence = 0.0
    motion: MotionState
    zone: str | None = None
    identity: IdentityAssignment
    crop_quality: CropQuality | None = None


class PerceptionFrame(Contract):
    """The only contract that a pixel-facing component may publish."""

    frame_id: str
    camera_id: str
    ts: datetime
    tracks: tuple[TrackObservation, ...] = ()
    quality: FrameQuality
    model_versions: dict[str, str] = Field(default_factory=dict)

    def track(self, track_id: int) -> TrackObservation | None:
        return next((t for t in self.tracks if t.track_id == track_id), None)
