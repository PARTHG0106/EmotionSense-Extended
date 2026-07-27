"""Configuration loading. No threshold may be hardcoded in application code.

Every tunable constant used by perception, activity, behaviour and reasoning lives in
``configs/default.yaml`` and is overridable per site by a local file.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Section(BaseModel):
    # Unknown keys are ignored rather than rejected so that operators can annotate
    # site configs without breaking deployment.
    model_config = ConfigDict(extra="ignore", frozen=True)


class CameraConfig(_Section):
    camera_id: str
    uri: str = ""
    zones: tuple[str, ...] = ()
    fps_target: int = 10
    enabled: bool = True


class SiteConfig(_Section):
    site_id: str = "demo-site"
    timezone: str = "Asia/Kolkata"


class CropQualityConfig(_Section):
    min_blur_score: float = 25.0
    min_height_px: float = 64.0
    max_truncation: float = 0.35


class DetectorConfig(_Section):
    backend: str = "stub"
    weights: str = ""
    device: str = "auto"
    conf_threshold: float = 0.35
    min_box_height_px: float = 48.0


class TrackerConfig(_Section):
    backend: str = "stub"
    max_age_frames: int = 60
    min_hits: int = 3
    iou_threshold: float = 0.3


class PoseConfig(_Section):
    backend: str = "stub"
    min_keypoint_conf: float = 0.30


class ReidConfig(_Section):
    backend: str = "stub"
    embedding_dim: int = 512
    index: str = "faiss_flat_ip"
    crop_quality: CropQualityConfig = CropQualityConfig()


class PerceptionConfig(_Section):
    detector: DetectorConfig = DetectorConfig()
    tracker: TrackerConfig = TrackerConfig()
    pose: PoseConfig = PoseConfig()
    reid: ReidConfig = ReidConfig()


class GalleryConfig(_Section):
    body_prototype_ttl_hours: float | None = 36.0
    face_prototype_ttl_hours: float | None = None
    max_prototypes_per_signal: int = 24


class VisitorConfig(_Section):
    enroll_in_gallery: bool = False
    purge_after_hours: float = 24.0


class IdentityConfig(_Section):
    signal_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "body": 0.35,
            "face": 0.30,
            "gait": 0.20,
            "anthropometry": 0.10,
            "spatiotemporal_prior": 0.05,
        }
    )
    accept_threshold: float = 0.72
    reject_threshold: float = 0.45
    hysteresis_frames: int = 15
    gallery: GalleryConfig = GalleryConfig()
    visitor: VisitorConfig = VisitorConfig()


class PostureRulesConfig(_Section):
    lying_torso_angle_deg: float = 55.0
    sitting_hip_knee_ratio: float = 0.55
    stillness_speed_px_s: float = 8.0


class FallConfig(_Section):
    centroid_drop_ratio: float = 0.40
    drop_window_seconds: float = 1.0
    horizontal_hold_seconds: float = 3.0
    post_event_stillness_seconds: float = 10.0
    require_model_agreement: bool = False
    model_confidence_floor: float = 0.60


class AdlConfig(_Section):
    backend: str = "stub"
    min_confidence: float = 0.55


class InactivityConfig(_Section):
    prolonged_minutes: float = 90.0
    night_prolonged_minutes: float = 480.0


class ActivityConfig(_Section):
    window_seconds: float = 4.0
    window_stride_seconds: float = 1.0
    min_event_duration_seconds: float = 3.0
    adl: AdlConfig = AdlConfig()
    posture: PostureRulesConfig = PostureRulesConfig()
    fall: FallConfig = FallConfig()
    inactivity: InactivityConfig = InactivityConfig()


class BaselineConfig(_Section):
    window_days: int = 14
    warmup_days: int = 14
    statistic: str = "median_mad"
    buckets: tuple[str, ...] = ("night", "morning", "afternoon", "evening")
    bucket_hours: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "night": (0, 6),
            "morning": (6, 12),
            "afternoon": (12, 18),
            "evening": (18, 24),
        }
    )
    separate_weekend: bool = True
    min_completeness: float = 0.60


class AnomalyConfig(_Section):
    methods: tuple[str, ...] = ("zscore", "isolation_forest")
    attention_sigma: float = 1.5
    warning_sigma: float = 2.5
    max_alerts_per_resident_per_day: int = 3


class TrendConfig(_Section):
    window_days: int = 28
    test: str = "mann_kendall"
    p_value: float = 0.05
    sustained_days_to_reclassify: int = 7


class BehaviorConfig(_Section):
    baseline: BaselineConfig = BaselineConfig()
    anomaly: AnomalyConfig = AnomalyConfig()
    trend: TrendConfig = TrendConfig()


class LlmConfig(_Section):
    backend: str = "template"
    model: str = "strongest-available"
    max_output_tokens: int = 400
    temperature: float = 0.2


class ReasoningConfig(_Section):
    llm: LlmConfig = LlmConfig()
    require_all_explanation_fields: bool = True
    banned_phrases: tuple[str, ...] = (
        "diagnosed",
        "has dementia",
        "is depressed",
        "symptoms of",
        "should take",
        "prescribe",
    )
    identity_confidence_floor: float = 0.60


class AlertsConfig(_Section):
    critical_ack_timeout_seconds: float = 60.0
    critical_kinds: tuple[str, ...] = (
        "fall",
        "prolonged_no_response",
        "night_unrecovered_lying",
    )
    never_rate_limit: tuple[str, ...] = ("fall",)


class RetentionConfig(_Section):
    raw_frames: str = "never_persisted"
    incident_clip_hours: float = 72.0
    keypoints_days: int = 30
    activity_events_days: int = 365
    daily_aggregates_days: int = 730


class StorageConfig(_Section):
    database_url: str = "postgresql+psycopg://wellbeing:wellbeing@localhost:5432/wellbeing"
    redis_url: str = "redis://localhost:6379/0"
    retention: RetentionConfig = RetentionConfig()
    encrypt_embeddings: bool = True


class RuntimeConfig(_Section):
    backpressure: str = "drop_to_latest"
    max_perception_latency_ms: float = 150.0
    degradation_ladder: tuple[str, ...] = (
        "full",
        "reduced_fps",
        "no_reid",
        "pose_safety_only",
        "ops_alert",
    )
    seed: int = 42


class AppConfig(_Section):
    site: SiteConfig = SiteConfig()
    cameras: tuple[CameraConfig, ...] = ()
    perception: PerceptionConfig = PerceptionConfig()
    identity: IdentityConfig = IdentityConfig()
    activity: ActivityConfig = ActivityConfig()
    behavior: BehaviorConfig = BehaviorConfig()
    reasoning: ReasoningConfig = ReasoningConfig()
    alerts: AlertsConfig = AlertsConfig()
    storage: StorageConfig = StorageConfig()
    runtime: RuntimeConfig = RuntimeConfig()


DEFAULT_CONFIG_PATH = Path("configs/default.yaml")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(*paths: Path | str) -> AppConfig:
    """Load and merge YAML configuration files, later files winning.

    With no arguments the packaged defaults are used, which is what tests rely on so
    that the whole system is runnable without any site configuration present.
    """
    candidates = [Path(p) for p in paths] or [DEFAULT_CONFIG_PATH]
    merged: dict[str, Any] = {}
    for path in candidates:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"config file {path} must contain a mapping at the top level")
        merged = _deep_merge(merged, data)
    return AppConfig.model_validate(merged)
