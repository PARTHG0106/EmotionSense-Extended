"""Pipeline orchestration.

The orchestrator wires the layers together without letting them know about each other:
it passes contracts, not objects. This is what makes it possible to replay a stored
perception trace and reproduce every alert without a GPU or a camera.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from wellbeing.activity.assembler import EventAssembler
from wellbeing.activity.fall import FallDetector, FallSample
from wellbeing.behavior.anomaly import AnomalyDetector
from wellbeing.behavior.baseline import BaselineBuilder
from wellbeing.behavior.features import FEATURE_METRICS, bucket_of, compute_daily_features
from wellbeing.behavior.trend import TrendAnalyzer
from wellbeing.config import AppConfig
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, EventSource
from wellbeing.contracts.alerts import Alert
from wellbeing.contracts.behavior import (
    AnomalySignal,
    Baseline,
    Bucket,
    DailyFeatures,
    DayType,
    TrendResult,
)
from wellbeing.contracts.common import TimeWindow
from wellbeing.contracts.perception import PerceptionFrame
from wellbeing.reasoning.alert_builder import AlertBuilder


@dataclass(slots=True)
class DayReview:
    """Result of the nightly behaviour review for one subject."""

    subject_id: str
    day: date
    features: list[DailyFeatures] = field(default_factory=list)
    baselines: dict[str, Baseline] = field(default_factory=dict)
    anomalies: list[AnomalySignal] = field(default_factory=list)
    trends: list[TrendResult] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)

    @property
    def actionable_alerts(self) -> list[Alert]:
        return [a for a in self.alerts if a.is_actionable]


class Pipeline:
    """Coordinates the four layers over a stream of perception frames."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._assembler = EventAssembler(config.activity)
        self._fall_detectors: dict[str, FallDetector] = {}
        self._baselines = BaselineBuilder(config.behavior.baseline)
        self._anomalies = AnomalyDetector(config.behavior.anomaly)
        self._trends = TrendAnalyzer(config.behavior.trend)
        self._alerts = AlertBuilder(config.alerts, config.reasoning)
        self._events: list[ActivityEvent] = []

    # ------------------------------------------------------------------ live path
    def process_frames(self, frames: Iterable[PerceptionFrame]) -> tuple[list[ActivityEvent], list[Alert]]:
        """Run the live path: events plus any immediate safety-critical alerts."""
        events: list[ActivityEvent] = []
        alerts: list[Alert] = []
        for frame in frames:
            alerts.extend(self._check_falls(frame))
            for sample in self._assembler.samples_from_frame(frame):
                event = self._assembler.push(sample)
                if event is not None:
                    events.append(event)
        events.extend(self._assembler.flush())
        self._events.extend(events)
        return events, alerts

    def _check_falls(self, frame: PerceptionFrame) -> list[Alert]:
        alerts: list[Alert] = []
        for track in frame.tracks:
            detector = self._fall_detectors.setdefault(
                track.identity.subject_id, FallDetector(self._config.activity.fall)
            )
            assessment = detector.update(
                FallSample(
                    ts=frame.ts,
                    centroid_y=track.bbox.center[1],
                    body_height=max(track.bbox.height, track.bbox.width),
                    torso_angle_deg=None,
                    posture=track.posture,
                    speed_px_s=track.motion.speed_px_s,
                )
            )
            if not assessment.detected:
                continue
            event = ActivityEvent(
                event_id=f"fall_{frame.frame_id}",
                subject_id=track.identity.subject_id,
                subject_kind=track.identity.kind,
                camera_id=frame.camera_id,
                zone=track.zone,
                label=ActivityLabel.FALL,
                window=TimeWindow(start=frame.ts, end=frame.ts),
                confidence=assessment.confidence,
                identity_confidence=track.identity.confidence,
                source=EventSource.POSE_RULE,
                evidence=(frame.frame_id, *assessment.rules_fired),
                model_versions=frame.model_versions,
            )
            self._events.append(event)
            alerts.append(self._alerts.from_fall(event, assessment, track.identity))
            detector.reset()
        return alerts

    # ----------------------------------------------------------------- batch path
    def review_day(
        self,
        subject_id: str,
        day: date,
        history: Sequence[DailyFeatures] = (),
        now: datetime | None = None,
        completeness: float = 1.0,
    ) -> DayReview:
        """Nightly review: features, baselines, anomalies, trends and alerts."""
        moment = now or datetime.combine(day, datetime.min.time())
        review = DayReview(subject_id=subject_id, day=day)
        baseline_config = self._config.behavior.baseline

        for bucket in (Bucket(b) for b in baseline_config.buckets):
            features = compute_daily_features(
                self._events, subject_id, day, bucket, baseline_config, completeness
            )
            review.features.append(features)
            baselines = self._baselines.build_all(
                subject_id,
                FEATURE_METRICS,
                history,
                bucket,
                DayType.of(day),
                moment,
            )
            review.baselines.update(
                {f"{bucket.value}:{metric}": b for metric, b in baselines.items()}
            )
            evidence = tuple(
                e.event_id
                for e in self._events
                if e.subject_id == subject_id
                and e.window.start.date() == day
                and bucket_of(e.window.start, baseline_config) is bucket
            )
            review.anomalies.extend(
                self._anomalies.evaluate(features, baselines, evidence)
            )

        for metric in FEATURE_METRICS:
            trend = self._trends.analyse(subject_id, metric, history)
            if trend.is_significant:
                review.trends.append(trend)

        trend_by_metric = {t.metric: t for t in review.trends}
        for anomaly in self._anomalies.rank_and_cap(review.anomalies):
            review.alerts.append(
                self._alerts.from_anomaly(anomaly, trend=trend_by_metric.get(anomaly.metric))
            )
        return review

    @property
    def events(self) -> list[ActivityEvent]:
        return list(self._events)
