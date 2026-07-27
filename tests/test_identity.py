from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from wellbeing.config import IdentityConfig
from wellbeing.contracts.common import SubjectKind
from wellbeing.contracts.perception import IdentitySignal
from wellbeing.perception.identity import IdentityResolver

NOW = datetime(2026, 3, 2, 10, 0, 0)
DIM = 64


def _vector(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    vec = rng.normal(size=DIM).astype(np.float32)
    return vec / np.linalg.norm(vec)


def _resolver(**overrides: object) -> IdentityResolver:
    return IdentityResolver(IdentityConfig(**overrides))  # type: ignore[arg-type]


def test_enrolled_resident_is_matched() -> None:
    resolver = _resolver()
    body = _vector(1)
    resolver.enroll("resident:ana", IdentitySignal.BODY, body, NOW)
    resolver.enroll("resident:ana", IdentitySignal.FACE, _vector(2), NOW)

    assignment = resolver.resolve(
        1, {IdentitySignal.BODY: body, IdentitySignal.FACE: _vector(2)}, NOW
    )
    assert assignment.kind is SubjectKind.RESIDENT
    assert assignment.subject_id == "resident:ana"
    assert assignment.confidence >= 0.72


def test_stranger_is_unknown_not_a_guess() -> None:
    """A wrong identity corrupts a baseline permanently, so low confidence must abstain."""
    resolver = _resolver()
    resolver.enroll("resident:ana", IdentitySignal.BODY, _vector(1), NOW)

    assignment = resolver.resolve(9, {IdentitySignal.BODY: _vector(999)}, NOW)
    assert assignment.kind is SubjectKind.UNKNOWN
    assert assignment.subject_id.startswith("visitor:")
    assert not assignment.supports_behavior_claims(0.6)


def test_missing_signal_degrades_gracefully() -> None:
    """A back-facing track loses face evidence; that must not read as a stranger."""
    resolver = _resolver()
    body = _vector(3)
    resolver.enroll("resident:bo", IdentitySignal.BODY, body, NOW)
    resolver.enroll("resident:bo", IdentitySignal.FACE, _vector(4), NOW)

    body_only = resolver.resolve(2, {IdentitySignal.BODY: body}, NOW)
    assert body_only.subject_id == "resident:bo"
    assert body_only.signals_used == (IdentitySignal.BODY,)
    assert body_only.confidence >= 0.72


def test_hysteresis_prevents_instant_identity_switch() -> None:
    resolver = _resolver(hysteresis_frames=5)
    ana, bo = _vector(10), _vector(11)
    resolver.enroll("resident:ana", IdentitySignal.BODY, ana, NOW)
    resolver.enroll("resident:bo", IdentitySignal.BODY, bo, NOW)

    for _ in range(3):
        resolver.resolve(7, {IdentitySignal.BODY: ana}, NOW)

    # Two contradicting frames must not flip an established identity.
    for _ in range(2):
        held = resolver.resolve(7, {IdentitySignal.BODY: bo}, NOW)
        assert held.subject_id == "resident:ana"

    for _ in range(5):
        switched = resolver.resolve(7, {IdentitySignal.BODY: bo}, NOW)
    assert switched.subject_id == "resident:bo"


def test_body_prototypes_expire_but_face_prototypes_do_not() -> None:
    """Clothing changes daily; facial appearance does not."""
    resolver = _resolver()
    resolver.enroll("resident:ana", IdentitySignal.BODY, _vector(1), NOW)
    resolver.enroll("resident:ana", IdentitySignal.FACE, _vector(2), NOW)
    assert resolver.gallery_size == 2

    resolver.purge_expired(NOW + timedelta(hours=48))
    assert resolver.gallery_size == 1


def test_gallery_is_capped_per_signal() -> None:
    resolver = _resolver()
    for seed in range(40):
        resolver.enroll("resident:ana", IdentitySignal.FACE, _vector(seed), NOW)
    assert resolver.gallery_size <= 24
