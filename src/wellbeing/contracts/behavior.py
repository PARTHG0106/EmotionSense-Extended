"""L3 behaviour contracts: personal baselines, deviations and trends."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import Field

from wellbeing.contracts.common import Confidence, Contract, Severity, TimeWindow

#: Robust-sigma conversion factor for the median absolute deviation of a normal sample.
MAD_TO_SIGMA = 1.4826


class Bucket(StrEnum):
    """Time-of-day bucket. Baselines are per bucket: 3 a.m. is not comparable to 3 p.m."""

    NIGHT = "night"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class DayType(StrEnum):
    WEEKDAY = "weekday"
    WEEKEND = "weekend"

    @classmethod
    def of(cls, day: date) -> DayType:
        return cls.WEEKEND if day.weekday() >= 5 else cls.WEEKDAY


class DailyFeatures(Contract):
    """Aggregated behaviour for one subject, one day, one bucket."""

    subject_id: str
    day: date
    bucket: Bucket
    features: dict[str, float]
    completeness: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def day_type(self) -> DayType:
        return DayType.of(self.day)

    def is_baseline_eligible(self, min_completeness: float) -> bool:
        """A camera outage day must be excluded, never counted as zero activity.

        Conflating "no data" with "no activity" is the single most common source of false
        'resident was inactive all day' alerts in systems like this.
        """
        return self.completeness >= min_completeness


class BaselineStatus(StrEnum):
    FORMING = "forming"
    STABLE = "stable"
    DRIFTING = "drifting"


class Baseline(Contract):
    """Robust personal baseline for one metric, bucket and day type."""

    subject_id: str
    metric: str
    bucket: Bucket
    day_type: DayType
    median: float
    mad: float = Field(ge=0.0)
    n_days: int = Field(ge=0)
    status: BaselineStatus
    updated_at: datetime

    @property
    def robust_sigma(self) -> float:
        """Scale estimate used for deviations.

        A zero MAD (a perfectly regular resident) would make every tiny change infinitely
        anomalous, so a floor proportional to the median is applied.
        """
        sigma = self.mad * MAD_TO_SIGMA
        floor = max(abs(self.median) * 0.10, 1e-6)
        return max(sigma, floor)

    def deviation_sigma(self, observed: float) -> float:
        return (observed - self.median) / self.robust_sigma

    @property
    def is_usable(self) -> bool:
        return self.status is not BaselineStatus.FORMING


class AnomalyMethod(StrEnum):
    ZSCORE = "zscore"
    ISOLATION_FOREST = "isolation_forest"
    AUTOENCODER = "autoencoder"
    TEMPORAL_TRANSFORMER = "temporal_transformer"


class AnomalySignal(Contract):
    """A quantified deviation from this resident's own baseline."""

    anomaly_id: str
    subject_id: str
    window: TimeWindow
    metric: str
    bucket: Bucket
    observed: float
    baseline_median: float
    deviation_sigma: float
    score: Confidence
    method: AnomalyMethod
    severity: Severity
    evidence_event_ids: tuple[str, ...] = ()

    @property
    def direction(self) -> str:
        return "higher" if self.deviation_sigma > 0 else "lower"

    @property
    def absolute_delta(self) -> float:
        return abs(self.observed - self.baseline_median)


class TrendDirection(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


class TrendResult(Contract):
    """Monotonic trend over a multi-week window."""

    subject_id: str
    metric: str
    window_days: int
    direction: TrendDirection
    slope_per_day: float
    p_value: float = Field(ge=0.0, le=1.0)
    n_points: int = Field(ge=0)
    statement: str = ""

    @property
    def is_significant(self) -> bool:
        return self.direction is not TrendDirection.STABLE


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class BehaviorProfile(Contract):
    """Rolled-up behavioural state for a resident.

    ``wellbeing_score`` is an operational indicator, not a clinical instrument. It is
    always presented with its component breakdown so it can be challenged.
    """

    subject_id: str
    generated_at: datetime
    wellbeing_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    components: dict[str, float] = Field(default_factory=dict)
    baselines: tuple[Baseline, ...] = ()
    trends: tuple[TrendResult, ...] = ()
    anomalies: tuple[AnomalySignal, ...] = ()
    baseline_forming: bool = False
