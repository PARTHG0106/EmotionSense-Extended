"""Explanation construction.

Explainability is treated as a data requirement. The six fields are filled deterministically
from upstream rows; prose is rendered afterwards from those fields. If the language model is
unavailable or produces a banned phrase, the alert still ships as a structured card, so an
LLM failure degrades presentation and never correctness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from wellbeing.behavior.features import metric_units
from wellbeing.config import ReasoningConfig
from wellbeing.contracts.activity import ActivityEvent, ActivityLabel, FallAssessment
from wellbeing.contracts.alerts import AlertKind, Explanation
from wellbeing.contracts.behavior import AnomalySignal, TrendResult
from wellbeing.contracts.perception import IdentityAssignment


class GroundingViolation(RuntimeError):
    """Raised when generated text is not supported by its structured input."""


#: Curated caregiver actions. Deliberately a lookup table, not model output: this is the
#: field most likely to drift into clinical advice if a model is allowed to invent it.
CHECK_NEXT_PLAYBOOK: Mapping[AlertKind, str] = {
    AlertKind.FALL: "Go to the resident now and check for injury and responsiveness.",
    AlertKind.PROLONGED_INACTIVITY: (
        "Check on the resident in person and confirm they are comfortable and responsive."
    ),
    AlertKind.PROLONGED_NO_RESPONSE: "Attend in person immediately and escalate if unresponsive.",
    AlertKind.NIGHT_UNRECOVERED_LYING: "Check the bedroom and confirm the resident can get up.",
    AlertKind.ROUTINE_DEVIATION: (
        "Ask the resident how they are feeling today and note anything unusual."
    ),
    AlertKind.MOBILITY_DECLINE: (
        "Review walking and sit-to-stand counts with the nurse at the next handover."
    ),
    AlertKind.REST_DISRUPTION: "Ask about sleep quality and check the room at night.",
    AlertKind.MISSED_MEAL_PATTERN: "Confirm meals and fluid intake with the resident.",
    AlertKind.IDENTITY_UNCERTAIN: (
        "Confirm who is present. Camera view or lighting may need adjustment."
    ),
    AlertKind.SYSTEM_DEGRADED: "Check camera and device status; monitoring is reduced.",
}


def check_banned_phrases(text: str, banned: Sequence[str]) -> tuple[str, ...]:
    """Return any banned clinical phrases present in ``text``.

    This runs before anything reaches a caregiver. The system reports observations and risk
    signals; it does not diagnose, and it must not be able to phrase itself as if it does.
    """
    lowered = text.lower()
    return tuple(phrase for phrase in banned if phrase.lower() in lowered)


def _humanise_minutes(minutes: float) -> str:
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{round(minutes)} minutes"
    hours = minutes / 60.0
    if abs(hours - round(hours)) < 0.1:
        return f"{round(hours)} hours"
    return f"{hours:.1f} hours"


class Explainer:
    """Builds the six-field explanation for each alert kind."""

    def __init__(self, config: ReasoningConfig) -> None:
        self._config = config
        self._units = metric_units()

    # ---------------------------------------------------------------- confidence
    def _confidence_sentence(
        self, model_confidence: float, identity: IdentityAssignment | None
    ) -> str:
        """Always name the weakest link, so caregivers can calibrate their own trust."""
        label = "high" if model_confidence >= 0.8 else "moderate" if model_confidence >= 0.6 else "low"
        sentence = f"{label.capitalize()} ({model_confidence:.0%})."
        if identity is None:
            return sentence
        sentence += f" Identity confidence {identity.confidence:.0%}"
        weakest = identity.weakest_signal
        if weakest is not None:
            sentence += f", weakest signal was {weakest.value.replace('_', ' ')}"
        return sentence + "."

    # ------------------------------------------------------------------- builders
    def for_fall(
        self,
        event: ActivityEvent,
        assessment: FallAssessment,
        identity: IdentityAssignment | None = None,
    ) -> Explanation:
        where = event.zone or event.camera_id
        return Explanation(
            what=f"A possible fall was detected in the {where.replace('_', ' ')}.",
            when=event.window.start.strftime("%d %b %Y at %H:%M"),
            why_flagged=(
                "Kinematic fall signature: "
                + ", ".join(r.replace("_", " ") for r in assessment.rules_fired)
                + f". {assessment.reason}."
            ),
            baseline_delta=(
                "Not a baseline comparison. This is a safety-critical event detected "
                "directly from movement."
            ),
            confidence=self._confidence_sentence(assessment.confidence, identity),
            check_next=CHECK_NEXT_PLAYBOOK[AlertKind.FALL],
        )

    def for_anomaly(
        self,
        anomaly: AnomalySignal,
        kind: AlertKind,
        identity: IdentityAssignment | None = None,
        trend: TrendResult | None = None,
    ) -> Explanation:
        unit = self._units.get(anomaly.metric, anomaly.metric.replace("_", " "))
        delta = anomaly.absolute_delta
        direction = "below" if anomaly.deviation_sigma < 0 else "above"
        baseline_delta = (
            f"{anomaly.observed:.0f} {unit} this {anomaly.bucket.value}, "
            f"{delta:.0f} {direction} their usual {anomaly.baseline_median:.0f} "
            f"({abs(anomaly.deviation_sigma):.1f} sigma from their own baseline)."
        )
        if trend is not None and trend.is_significant:
            baseline_delta += f" {trend.statement}"
        return Explanation(
            what=(
                f"{unit.capitalize()} was {direction} this resident's normal "
                f"{anomaly.bucket.value} pattern."
            ),
            when=anomaly.window.start.strftime("%d %b %Y") + f", {anomaly.bucket.value}",
            why_flagged=(
                f"Measured {anomaly.metric.replace('_', ' ')} deviated "
                f"{abs(anomaly.deviation_sigma):.1f} sigma from this resident's "
                f"{anomaly.bucket.value} baseline."
            ),
            baseline_delta=baseline_delta,
            confidence=self._confidence_sentence(anomaly.score, identity),
            check_next=CHECK_NEXT_PLAYBOOK.get(
                kind, CHECK_NEXT_PLAYBOOK[AlertKind.ROUTINE_DEVIATION]
            ),
        )

    def for_inactivity(
        self,
        event: ActivityEvent,
        baseline_minutes: float | None,
        identity: IdentityAssignment | None = None,
    ) -> Explanation:
        duration = _humanise_minutes(event.duration_minutes)
        where = (event.zone or event.camera_id).replace("_", " ")
        if baseline_minutes is None:
            baseline_delta = (
                "No stable baseline yet for this time of day; flagged on duration alone."
            )
        else:
            extra = max(0.0, event.duration_minutes - baseline_minutes)
            baseline_delta = (
                f"{_humanise_minutes(extra)} longer than their usual "
                f"{_humanise_minutes(baseline_minutes)} for this time of day."
            )
        return Explanation(
            what=f"The resident stayed inactive in the {where} for {duration}.",
            when=(
                event.window.start.strftime("%d %b %Y at %H:%M")
                + " to "
                + event.window.end.strftime("%H:%M")
            ),
            why_flagged=(
                f"Continuous {event.label.value.replace('_', ' ')} with no posture change "
                f"or room movement for {duration}."
            ),
            baseline_delta=baseline_delta,
            confidence=self._confidence_sentence(event.confidence, identity),
            check_next=CHECK_NEXT_PLAYBOOK[AlertKind.PROLONGED_INACTIVITY],
        )

    def for_low_identity(self, identity: IdentityAssignment) -> Explanation:
        return Explanation(
            what="Someone was detected but could not be identified with confidence.",
            when="now",
            why_flagged=(
                f"Fused identity confidence was {identity.confidence:.0%}, below the "
                f"{self._config.identity_confidence_floor:.0%} floor required for "
                "behavioural claims."
            ),
            baseline_delta=(
                "Behavioural comparisons are withheld because they would be attributed to "
                "the wrong person."
            ),
            confidence=self._confidence_sentence(identity.confidence, identity),
            check_next=CHECK_NEXT_PLAYBOOK[AlertKind.IDENTITY_UNCERTAIN],
        )

    # ----------------------------------------------------------------- rendering
    def render_prose(self, explanation: Explanation) -> str:
        """Deterministic renderer used as the default and as the LLM fallback."""
        if self._config.require_all_explanation_fields and not explanation.is_complete:
            raise GroundingViolation(
                f"explanation missing required fields: {explanation.missing_fields}"
            )
        text = (
            f"{explanation.what} {explanation.when}. {explanation.baseline_delta} "
            f"{explanation.confidence} Next: {explanation.check_next}"
        )
        violations = check_banned_phrases(text, self._config.banned_phrases)
        if violations:
            raise GroundingViolation(f"banned clinical phrasing: {violations}")
        return " ".join(text.split())

    def validate_generated(self, text: str, explanation: Explanation) -> str:
        """Gate for text produced by an external language model.

        Falls back to the deterministic renderer rather than shipping unvalidated prose.
        """
        if not text.strip():
            return self.render_prose(explanation)
        if check_banned_phrases(text, self._config.banned_phrases):
            return self.render_prose(explanation)
        return text.strip()
