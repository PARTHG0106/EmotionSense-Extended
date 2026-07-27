"""L4 reasoning: structured rows in, grounded caregiver-facing text out.

The language model in this layer never sees a frame, never detects anything, and may not
introduce a fact that is absent from its structured input. It renders; it does not decide.
"""

from wellbeing.reasoning.alert_builder import AlertBuilder
from wellbeing.reasoning.explainer import (
    CHECK_NEXT_PLAYBOOK,
    Explainer,
    GroundingViolation,
    check_banned_phrases,
)

__all__ = [
    "CHECK_NEXT_PLAYBOOK",
    "AlertBuilder",
    "Explainer",
    "GroundingViolation",
    "check_banned_phrases",
]
