from __future__ import annotations

from datetime import date, datetime, timedelta

from wellbeing.behavior.anomaly import AnomalyDetector
from wellbeing.behavior.baseline import BaselineBuilder
from wellbeing.behavior.trend import TrendAnalyzer, mann_kendall
from wellbeing.config import AnomalyConfig, BaselineConfig, TrendConfig
from wellbeing.contracts.behavior import (
    BaselineStatus,
    Bucket,
    DailyFeatures,
    DayType,
    TrendDirection,
)
from wellbeing.contracts.common import Severity

NOW = datetime(2026, 3, 20, 23, 0, 0)
SUBJECT = "resident:ana"


def _history(
    values: list[float],
    metric: str = "active_minutes",
    bucket: Bucket = Bucket.AFTERNOON,
    completeness: float = 1.0,
    start: date = date(2026, 3, 2),
) -> list[DailyFeatures]:
    return [
        DailyFeatures(
            subject_id=SUBJECT,
            day=start + timedelta(days=i),
            bucket=bucket,
            features={metric: value},
            completeness=completeness,
        )
        for i, value in enumerate(values)
    ]


def test_baseline_is_forming_during_warmup() -> None:
    """Alerting on a three-day 'baseline' produces nothing but noise."""
    builder = BaselineBuilder(BaselineConfig(separate_weekend=False))
    baseline = builder.build(
        SUBJECT, "active_minutes", _history([60, 62, 58]), Bucket.AFTERNOON, DayType.WEEKDAY, NOW
    )
    assert baseline.status is BaselineStatus.FORMING
    assert not baseline.is_usable


def test_baseline_is_robust_to_a_single_outlier_day() -> None:
    """One hospital day must not reshape a resident's baseline."""
    builder = BaselineBuilder(BaselineConfig(separate_weekend=False))
    values = [60.0] * 13 + [0.0]
    baseline = builder.build(
        SUBJECT, "active_minutes", _history(values), Bucket.AFTERNOON, DayType.WEEKDAY, NOW
    )
    assert baseline.status is BaselineStatus.STABLE
    assert baseline.median == 60.0


def test_low_completeness_days_are_excluded() -> None:
    builder = BaselineBuilder(BaselineConfig(separate_weekend=False))
    baseline = builder.build(
        SUBJECT,
        "active_minutes",
        _history([60.0] * 14, completeness=0.1),
        Bucket.AFTERNOON,
        DayType.WEEKDAY,
        NOW,
    )
    assert baseline.n_days == 0


def test_reduced_activity_raises_an_anomaly_and_increased_activity_does_not() -> None:
    builder = BaselineBuilder(BaselineConfig(separate_weekend=False))
    history = _history([60.0, 58.0, 62.0, 61.0, 59.0, 60.0, 63.0] * 2)
    baselines = {
        "active_minutes": builder.build(
            SUBJECT, "active_minutes", history, Bucket.AFTERNOON, DayType.WEEKDAY, NOW
        )
    }
    detector = AnomalyDetector(AnomalyConfig())

    quiet = DailyFeatures(
        subject_id=SUBJECT,
        day=date(2026, 3, 20),
        bucket=Bucket.AFTERNOON,
        features={"active_minutes": 20.0},
    )
    signals = detector.evaluate(quiet, baselines)
    assert signals and signals[0].severity in (Severity.ATTENTION, Severity.WARNING)
    assert signals[0].direction == "lower"

    busy = quiet.model_copy(update={"features": {"active_minutes": 120.0}})
    assert detector.evaluate(busy, baselines) == []


def test_anomalies_are_capped_to_prevent_alert_fatigue() -> None:
    detector = AnomalyDetector(AnomalyConfig(max_alerts_per_resident_per_day=3))
    builder = BaselineBuilder(BaselineConfig(separate_weekend=False))
    metrics = [
        "active_minutes",
        "walking_minutes",
        "walking_bouts",
        "sit_to_stand_transitions",
        "meal_events",
    ]
    baselines = {}
    for metric in metrics:
        baselines[metric] = builder.build(
            SUBJECT, metric, _history([50.0] * 14, metric=metric), Bucket.AFTERNOON, DayType.WEEKDAY, NOW
        )
    features = DailyFeatures(
        subject_id=SUBJECT,
        day=date(2026, 3, 20),
        bucket=Bucket.AFTERNOON,
        features={metric: 5.0 for metric in metrics},
    )
    assert len(detector.evaluate(features, baselines)) == 3


def test_mann_kendall_detects_a_steady_decline() -> None:
    declining = [float(30 - i) for i in range(28)]
    result = mann_kendall(declining)
    assert result.s < 0
    assert result.p_value < 0.05
    assert result.slope < 0


def test_trend_analyzer_reports_decline_in_plain_language() -> None:
    analyzer = TrendAnalyzer(TrendConfig())
    history = _history([float(40 - i) for i in range(28)])
    trend = analyzer.analyse(SUBJECT, "active_minutes", history)
    assert trend.direction is TrendDirection.DECLINING
    assert "steadily decreasing" in trend.statement
    assert "per week" in trend.statement


def test_stable_history_reports_no_trend() -> None:
    analyzer = TrendAnalyzer(TrendConfig())
    history = _history([60.0, 61.0, 59.0, 60.0, 61.0, 59.0, 60.0] * 4)
    trend = analyzer.analyse(SUBJECT, "active_minutes", history)
    assert trend.direction is TrendDirection.STABLE
    assert not trend.is_significant


def test_sustained_deviation_becomes_a_trend() -> None:
    analyzer = TrendAnalyzer(TrendConfig(sustained_days_to_reclassify=7))
    assert not analyzer.is_sustained_deviation(3)
    assert analyzer.is_sustained_deviation(8)
