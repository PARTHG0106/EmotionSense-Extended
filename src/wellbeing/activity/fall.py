"""Rule-first fall detection.

Design position: published vision fall-detection scores come from staged falls performed
by young actors in clear view, and they do not survive real homes. The kinematic rule below
is therefore the primary detector - it is explainable, needs no site training data, and
bounds behaviour on unseen footage. A learned model may only adjust confidence.

Signature required for a fall:

1. vertical drop of the hip/shoulder centroid > ``centroid_drop_ratio`` x body height
   within ``drop_window_seconds``;
2. sustained near-horizontal torso for ``horizontal_hold_seconds``;
3. post-event stillness beyond ``post_event_stillness_seconds`` with no self-recovery.

Step 3 is what separates a fall from lying down on a sofa, and it is why this detector
never fires from a single frame.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from wellbeing.config import FallConfig
from wellbeing.contracts.activity import FallAssessment
from wellbeing.contracts.perception import Posture


@dataclass(frozen=True, slots=True)
class FallSample:
    """One temporal sample of the quantities the fall rule needs."""

    ts: datetime
    centroid_y: float
    body_height: float
    torso_angle_deg: float | None
    posture: Posture
    speed_px_s: float


class FallDetector:
    """Sliding-window kinematic fall detector for a single track."""

    def __init__(self, config: FallConfig, history_seconds: float = 30.0) -> None:
        self._config = config
        self._history_seconds = history_seconds
        self._samples: deque[FallSample] = deque()
        self._latched_at: datetime | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._latched_at = None

    def _trim(self, now: datetime) -> None:
        horizon = self._history_seconds
        while self._samples and (now - self._samples[0].ts).total_seconds() > horizon:
            self._samples.popleft()

    def update(
        self, sample: FallSample, model_confidence: float | None = None
    ) -> FallAssessment:
        """Feed one sample and return the current assessment."""
        self._samples.append(sample)
        self._trim(sample.ts)
        return self._assess(model_confidence)

    def ingest(
        self, samples: Iterable[FallSample], model_confidence: float | None = None
    ) -> FallAssessment:
        assessment = FallAssessment(detected=False, confidence=0.0, reason="no samples")
        for sample in samples:
            assessment = self.update(sample, model_confidence)
            if assessment.detected:
                return assessment
        return assessment

    # ------------------------------------------------------------------ rule logic
    def _drop(self) -> tuple[float, float]:
        """Largest normalised centroid drop inside the configured window."""
        window = self._config.drop_window_seconds
        best_ratio, best_seconds = 0.0, 0.0
        samples = list(self._samples)
        for i, start in enumerate(samples):
            for end in samples[i + 1 :]:
                elapsed = (end.ts - start.ts).total_seconds()
                if elapsed <= 0:
                    continue
                if elapsed > window:
                    break
                height = max(start.body_height, 1e-6)
                # Image y grows downward, so a positive delta is a downward drop.
                ratio = (end.centroid_y - start.centroid_y) / height
                if ratio > best_ratio:
                    best_ratio, best_seconds = ratio, elapsed
        return best_ratio, best_seconds

    def _horizontal_hold(self) -> float:
        """Seconds of continuous near-horizontal torso at the end of the history."""
        seconds = 0.0
        previous: FallSample | None = None
        for sample in reversed(self._samples):
            horizontal = sample.posture is Posture.LYING or (
                sample.torso_angle_deg is not None and sample.torso_angle_deg >= 55.0
            )
            if not horizontal:
                break
            if previous is not None:
                seconds += (previous.ts - sample.ts).total_seconds()
            previous = sample
        return seconds

    def _stillness(self) -> float:
        seconds = 0.0
        previous: FallSample | None = None
        for sample in reversed(self._samples):
            if sample.speed_px_s > 8.0:
                break
            if previous is not None:
                seconds += (previous.ts - sample.ts).total_seconds()
            previous = sample
        return seconds

    def _self_recovered(self) -> bool:
        """True if the subject returned to an upright posture after going horizontal."""
        seen_horizontal = False
        for sample in self._samples:
            if sample.posture is Posture.LYING:
                seen_horizontal = True
            elif seen_horizontal and sample.posture in (Posture.STANDING, Posture.SITTING):
                return True
        return False

    def _assess(self, model_confidence: float | None) -> FallAssessment:
        config = self._config
        drop_ratio, drop_seconds = self._drop()
        hold = self._horizontal_hold()
        still = self._stillness()
        recovered = self._self_recovered()

        rules: list[str] = []
        if drop_ratio >= config.centroid_drop_ratio and drop_seconds <= config.drop_window_seconds:
            rules.append("rapid_centroid_drop")
        if hold >= config.horizontal_hold_seconds:
            rules.append("sustained_horizontal_torso")
        if still >= config.post_event_stillness_seconds:
            rules.append("post_event_stillness")
        if recovered:
            rules.append("self_recovery_observed")

        required = {"rapid_centroid_drop", "sustained_horizontal_torso"}
        detected = required.issubset(set(rules)) and not recovered

        if detected and config.require_model_agreement:
            if model_confidence is None or model_confidence < config.model_confidence_floor:
                return FallAssessment(
                    detected=False,
                    confidence=0.45,
                    rules_fired=tuple(rules),
                    drop_ratio=drop_ratio,
                    drop_seconds=drop_seconds,
                    horizontal_hold_seconds=hold,
                    stillness_seconds=still,
                    model_confidence=model_confidence,
                    reason="kinematic rules fired but the action model did not agree",
                    self_recovered=recovered,
                )

        confidence = 0.0
        if detected:
            confidence = 0.72
            if "post_event_stillness" in rules:
                confidence += 0.13
            if model_confidence is not None:
                confidence = min(1.0, confidence + 0.15 * model_confidence)
            confidence = min(confidence, 1.0)
            reason = (
                f"centroid dropped {drop_ratio:.2f} of body height in {drop_seconds:.1f}s, "
                f"torso stayed horizontal for {hold:.0f}s, stillness {still:.0f}s"
            )
        elif recovered:
            reason = "subject returned to an upright posture; treated as a voluntary transfer"
        elif rules:
            reason = f"partial evidence only ({', '.join(rules)})"
        else:
            reason = "no fall signature in the current window"

        return FallAssessment(
            detected=detected,
            confidence=confidence,
            rules_fired=tuple(rules),
            drop_ratio=drop_ratio,
            drop_seconds=drop_seconds,
            horizontal_hold_seconds=hold,
            stillness_seconds=still,
            model_confidence=model_confidence,
            reason=reason,
            self_recovered=recovered,
        )
