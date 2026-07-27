"""Personal baseline construction.

Median and MAD rather than mean and standard deviation, deliberately: one hospital day or
one family visit must not reshape a resident's baseline, and outliers are exactly the
events this system exists to flag.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import datetime

from wellbeing.config import BaselineConfig
from wellbeing.contracts.behavior import (
    Baseline,
    BaselineStatus,
    Bucket,
    DailyFeatures,
    DayType,
)


class BaselineBuilder:
    """Builds robust per-metric baselines from historical daily features."""

    def __init__(self, config: BaselineConfig) -> None:
        self._config = config

    def eligible(
        self,
        history: Sequence[DailyFeatures],
        bucket: Bucket,
        day_type: DayType,
    ) -> list[DailyFeatures]:
        """Filter history down to comparable, trustworthy days."""
        selected = [
            day
            for day in history
            if day.bucket is bucket
            and day.is_baseline_eligible(self._config.min_completeness)
            and (not self._config.separate_weekend or day.day_type is day_type)
        ]
        selected.sort(key=lambda d: d.day, reverse=True)
        return selected[: self._config.window_days]

    def build(
        self,
        subject_id: str,
        metric: str,
        history: Sequence[DailyFeatures],
        bucket: Bucket,
        day_type: DayType,
        now: datetime,
    ) -> Baseline:
        """Return a baseline for one metric.

        During the warmup period the baseline is returned with status ``FORMING``. Alerting
        code must check :attr:`Baseline.is_usable`; suppressing alerts for the first two
        weeks is intentional, because a one-day "baseline" produces nothing but noise.
        """
        days = self.eligible(history, bucket, day_type)
        values = [d.features[metric] for d in days if metric in d.features]

        if not values:
            return Baseline(
                subject_id=subject_id,
                metric=metric,
                bucket=bucket,
                day_type=day_type,
                median=0.0,
                mad=0.0,
                n_days=0,
                status=BaselineStatus.FORMING,
                updated_at=now,
            )

        median = float(statistics.median(values))
        mad = float(statistics.median([abs(v - median) for v in values]))
        status = (
            BaselineStatus.FORMING
            if len(values) < self._config.warmup_days
            else BaselineStatus.STABLE
        )
        return Baseline(
            subject_id=subject_id,
            metric=metric,
            bucket=bucket,
            day_type=day_type,
            median=median,
            mad=mad,
            n_days=len(values),
            status=status,
            updated_at=now,
        )

    def build_all(
        self,
        subject_id: str,
        metrics: Sequence[str],
        history: Sequence[DailyFeatures],
        bucket: Bucket,
        day_type: DayType,
        now: datetime,
    ) -> dict[str, Baseline]:
        return {
            metric: self.build(subject_id, metric, history, bucket, day_type, now)
            for metric in metrics
        }
