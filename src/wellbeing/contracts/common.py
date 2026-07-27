"""Primitives shared by every layer contract."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Confidences are always normalised. A model that cannot produce one must not emit a row.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Contract(BaseModel):
    """Base class for all inter-layer contracts: immutable and strict.

    Immutability matters here because a contract instance is passed across layer
    boundaries and stored as evidence. A mutated event would silently invalidate the
    explanation that cites it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Severity(StrEnum):
    """Alert severity. Colour is never the only carrier of this in the UI."""

    NORMAL = "normal"
    ATTENTION = "attention"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @property
    def requires_human_review(self) -> bool:
        return self in (Severity.WARNING, Severity.CRITICAL)


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.NORMAL: 0,
    Severity.ATTENTION: 1,
    Severity.WARNING: 2,
    Severity.CRITICAL: 3,
}


class SubjectKind(StrEnum):
    """Who a track belongs to.

    ``UNKNOWN`` is a first-class outcome, not an error. A wrong identity permanently
    corrupts a resident baseline, so the resolver prefers to say nothing.
    """

    RESIDENT = "resident"
    VISITOR = "visitor"
    UNKNOWN = "unknown"


class BBox(Contract):
    """Axis-aligned bounding box in pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float

    @model_validator(mode="after")
    def _check_order(self) -> BBox:
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("bbox must satisfy x2 > x1 and y2 > y1")
        return self

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def aspect_ratio(self) -> float:
        """Width over height. A ratio above ~1.0 is a strong lying-down prior."""
        return self.width / self.height


class Keypoint(Contract):
    """A single body keypoint. Names follow the COCO-17 convention."""

    name: str
    x: float
    y: float
    confidence: Confidence

    @property
    def is_reliable(self) -> bool:
        return self.confidence >= 0.3


class TimeWindow(Contract):
    """Closed time interval. Used by every event and aggregate in the system."""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check_order(self) -> TimeWindow:
        if self.end < self.start:
            raise ValueError("time window end must not precede start")
        return self

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    def overlaps(self, other: TimeWindow) -> bool:
        return self.start <= other.end and other.start <= self.end
