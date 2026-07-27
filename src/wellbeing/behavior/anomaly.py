"""Deviation scoring against a resident's own baseline.

A global threshold is the wrong tool here: 40 active minutes is normal for one resident
and alarming for another. Anomaly severity is therefore always expressed in robust sigmas
from that individual's own median, and a daily cap prevents alert fatigue.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, time

from wellbeing.config import AnomalyConfig
from wellbeing.contracts.behavior import (
    AnomalyMethod,
    AnomalySignal,
    Baseline,
    DailyFeatures,
)
from wellbeing.contracts.common import Severity, TimeWindow

#: Metrics where a *drop* is the concerning direction.
_LOWER_IS_WORSE = (
    "active_minutes",
    "walking_minutes",
    "walking_bouts",
    "sit_to_stand_transitions",
    "meal_events",
    "zone_changes",
)


class AnomalyDetector:
    """Baseline z-score detector, the interpretable core of the anomaly ensemble."""

    def __init__(self, config: AnomalyConfig) -> None:
        self._config = config

    def severity_for(self, sigma: float) -> Severity:
        magnitude = abs(sigma)
        if magnitude >= self._config.warning_sigma:
            return Severity.WARNING
        if magnitude >= self._config.attention_sigma:
            return Severity.ATTENTION
        return Severity.NORMAL

    def evaluate(
        self,
        features: DailyFeatures,
        baselines: Mapping[str, Baseline],
        evidence_event_ids: Sequence[str] = (),
    ) -> list[AnomalySignal]:
        """Score one bucket of daily features against the matching baselines."""
        window = TimeWindow(
            start=datetime.combine(features.day, time.min),
            end=datetime.combine(features.day, time.max),
        )
        signals: list[AnomalySignal] = []
        for metric, observed in features.features.items():
            baseline = baselines.get(metric)
            if baseline is None or not baseline.is_usable:
                # Warmup: no baseline, no anomaly. Silence with a reason beats noise.
                continue
            sigma = baseline.deviation_sigma(observed)
            severity = self.severity_for(sigma)
            if severity is Severity.NORMAL:
                continue
            if metric in _LOWER_IS_WORSE and sigma > 0:
                # More walking than usual is not a clinical concern worth an alert.
                continue
            signals.append(
                AnomalySignal(
                    anomaly_id=f"anom_{uuid.uuid4().hex[:16]}",
                    subject_id=features.subject_id,
                    window=window,
                    metric=metric,
                    bucket=features.bucket,
                    observed=observed,
                    baseline_median=baseline.median,
                    deviation_sigma=sigma,
                    score=min(1.0, abs(sigma) / (self._config.warning_sigma * 2)),
                    method=AnomalyMethod.ZSCORE,
                    severity=severity,
                    evidence_event_ids=tuple(evidence_event_ids),
                )
            )
        return self.rank_and_cap(signals)

    def rank_and_cap(self, signals: Sequence[AnomalySignal]) -> list[AnomalySignal]:
        """Keep only the strongest deviations, up to the configured daily cap.

        Alert fatigue is a clinical safety issue: a caregiver who receives eight low-grade
        notifications a day stops reading the ninth, which may be the fall.
        """
        ordered = sorted(signals, key=lambda s: abs(s.deviation_sigma), reverse=True)
        return ordered[: self._config.max_alerts_per_resident_per_day]
