"""Monotonic trend detection over multi-week windows.

A sustained deviation is not an anomaly to repeat daily; it is a trend to report once.
This module is what converts "walking is down again today" (noise, on day seven) into
"walking has declined steadily over four weeks" (a clinically useful statement).

Mann-Kendall is used because it is non-parametric, robust to outliers and short-gap
tolerant, which matches real monitoring data far better than linear regression.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from wellbeing.config import TrendConfig
from wellbeing.contracts.behavior import DailyFeatures, TrendDirection, TrendResult

#: Metrics where a downward slope is a decline rather than an improvement.
_LOWER_IS_WORSE = (
    "active_minutes",
    "walking_minutes",
    "walking_bouts",
    "sit_to_stand_transitions",
    "meal_events",
    "zone_changes",
)


@dataclass(frozen=True, slots=True)
class MannKendallResult:
    s: int
    z: float
    p_value: float
    slope: float
    n: int


def _theil_sen_slope(values: Sequence[float]) -> float:
    """Median of pairwise slopes: the robust companion to the Mann-Kendall test."""
    slopes = [
        (values[j] - values[i]) / (j - i)
        for i in range(len(values))
        for j in range(i + 1, len(values))
    ]
    return float(statistics.median(slopes)) if slopes else 0.0


def mann_kendall(values: Sequence[float]) -> MannKendallResult:
    """Two-sided Mann-Kendall trend test with a normal approximation.

    Implemented directly so the behaviour layer stays runnable without SciPy, which also
    keeps it importable inside the offline Kaggle training environment.
    """
    n = len(values)
    if n < 4:
        return MannKendallResult(s=0, z=0.0, p_value=1.0, slope=0.0, n=n)

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            delta = values[j] - values[i]
            s += (delta > 0) - (delta < 0)

    # Variance with a tie correction.
    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    tie_term = sum(c * (c - 1) * (2 * c + 5) for c in counts.values() if c > 1)
    variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if variance <= 0:
        return MannKendallResult(s=s, z=0.0, p_value=1.0, slope=0.0, n=n)

    if s > 0:
        z = (s - 1) / math.sqrt(variance)
    elif s < 0:
        z = (s + 1) / math.sqrt(variance)
    else:
        z = 0.0
    p_value = math.erfc(abs(z) / math.sqrt(2.0))
    return MannKendallResult(
        s=s,
        z=z,
        p_value=max(0.0, min(1.0, p_value)),
        slope=_theil_sen_slope(values),
        n=n,
    )


class TrendAnalyzer:
    """Produces caregiver-readable trend statements per metric."""

    def __init__(self, config: TrendConfig) -> None:
        self._config = config

    def analyse(
        self, subject_id: str, metric: str, history: Sequence[DailyFeatures]
    ) -> TrendResult:
        ordered = sorted(
            (d for d in history if metric in d.features), key=lambda d: d.day
        )[-self._config.window_days :]
        values = [d.features[metric] for d in ordered]
        result = mann_kendall(values)

        direction = TrendDirection.STABLE
        if result.p_value <= self._config.p_value and result.s != 0:
            rising = result.s > 0
            worse_when_falling = metric in _LOWER_IS_WORSE
            if rising:
                direction = (
                    TrendDirection.IMPROVING if worse_when_falling else TrendDirection.DECLINING
                )
            else:
                direction = (
                    TrendDirection.DECLINING if worse_when_falling else TrendDirection.IMPROVING
                )

        statement = self._statement(metric, direction, result, len(values))
        return TrendResult(
            subject_id=subject_id,
            metric=metric,
            window_days=self._config.window_days,
            direction=direction,
            slope_per_day=result.slope,
            p_value=result.p_value,
            n_points=len(values),
            statement=statement,
        )

    @staticmethod
    def _statement(
        metric: str, direction: TrendDirection, result: MannKendallResult, n: int
    ) -> str:
        readable = metric.replace("_", " ")
        if n < 4:
            return f"Not enough history yet to judge a trend in {readable} ({n} days)."
        if direction is TrendDirection.STABLE:
            return f"{readable.capitalize()} has been stable over the last {n} days."
        change_per_week = result.slope * 7
        word = "decreasing" if result.slope < 0 else "increasing"
        return (
            f"{readable.capitalize()} has been steadily {word} over the last {n} days "
            f"({change_per_week:+.1f} per week, p={result.p_value:.3f})."
        )

    def is_sustained_deviation(self, consecutive_days: int) -> bool:
        """Whether a repeated daily deviation should be reclassified as a trend.

        Without this rule the system re-alerts every single day on the same underlying
        change, which is precisely how caregivers learn to ignore it.
        """
        return consecutive_days >= self._config.sustained_days_to_reclassify
