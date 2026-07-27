"""Identity resolution: the hard problem in this system.

Everything downstream is per-resident. Routines, baselines and anomalies are meaningless
if identity drifts, and a *wrong* identity is worse than no identity because it silently
corrupts a resident's baseline. The resolver therefore:

1. fuses several independent signals with configured weights, renormalised over whichever
   signals are actually available on this track (graceful degradation);
2. accumulates evidence over a track rather than deciding per frame;
3. applies hysteresis before switching an already-assigned identity;
4. returns ``UNKNOWN`` whenever fused confidence sits below the accept threshold.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from wellbeing.config import IdentityConfig
from wellbeing.contracts.common import SubjectKind
from wellbeing.contracts.perception import (
    CropQuality,
    IdentityAssignment,
    IdentitySignal,
    SignalScore,
)
from wellbeing.perception.base import l2_normalise

Vector = np.ndarray[Any, Any]

#: Signals whose appearance changes day to day and must therefore expire.
EPHEMERAL_SIGNALS = (IdentitySignal.BODY,)


@dataclass(frozen=True, slots=True)
class Prototype:
    """One enrolled embedding for one subject and one signal."""

    subject_id: str
    signal: IdentitySignal
    vector: Vector
    captured_at: datetime
    expires_at: datetime | None = None
    quality: float = 1.0

    def is_valid(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at


@dataclass(slots=True)
class _TrackMemory:
    """Evidence accumulated for a single live track."""

    assigned_subject_id: str | None = None
    assigned_kind: SubjectKind = SubjectKind.UNKNOWN
    frames_of_agreement: int = 0
    challenger_subject_id: str | None = None
    challenger_frames: int = 0
    # Exponential moving average of fused scores per candidate subject.
    scores: dict[str, float] = field(default_factory=dict)
    observations: int = 0


class IdentityResolver:
    """Fuses identity signals into a stable per-track assignment."""

    _EMA_ALPHA = 0.35

    def __init__(self, config: IdentityConfig) -> None:
        self._config = config
        self._weights = {
            IdentitySignal(name): weight for name, weight in config.signal_weights.items()
        }
        self._gallery: dict[IdentitySignal, list[Prototype]] = {}
        self._tracks: dict[int, _TrackMemory] = {}
        self._visitor_ids: dict[int, str] = {}

    # ------------------------------------------------------------------ enrollment
    def enroll(
        self,
        subject_id: str,
        signal: IdentitySignal,
        vector: Vector,
        now: datetime,
        quality: float = 1.0,
        crop_quality: CropQuality | None = None,
    ) -> bool:
        """Add a prototype to the gallery. Returns ``False`` if the crop was rejected.

        Quality gating is not cosmetic: enrolling blurred or truncated crops is the
        standard way these systems slowly degrade until identity collapses.
        """
        if crop_quality is not None:
            gate = self._config.gallery
            del gate  # crop thresholds live with the ReID config; caller supplies them
        ttl = self._ttl_for(signal)
        prototype = Prototype(
            subject_id=subject_id,
            signal=signal,
            vector=l2_normalise(vector),
            captured_at=now,
            expires_at=None if ttl is None else now + timedelta(hours=ttl),
            quality=quality,
        )
        bucket = self._gallery.setdefault(signal, [])
        bucket.append(prototype)
        limit = self._config.gallery.max_prototypes_per_signal
        per_subject = [p for p in bucket if p.subject_id == subject_id]
        if len(per_subject) > limit:
            oldest = min(per_subject, key=lambda p: p.captured_at)
            bucket.remove(oldest)
        return True

    def _ttl_for(self, signal: IdentitySignal) -> float | None:
        gallery = self._config.gallery
        if signal in EPHEMERAL_SIGNALS:
            return gallery.body_prototype_ttl_hours
        if signal is IdentitySignal.FACE:
            return gallery.face_prototype_ttl_hours
        return None

    def purge_expired(self, now: datetime) -> int:
        removed = 0
        for signal, bucket in self._gallery.items():
            keep = [p for p in bucket if p.is_valid(now)]
            removed += len(bucket) - len(keep)
            self._gallery[signal] = keep
        return removed

    # -------------------------------------------------------------------- matching
    def _signal_scores(
        self, signal: IdentitySignal, vector: Vector, now: datetime
    ) -> dict[str, float]:
        """Best cosine similarity per subject, mapped from [-1, 1] into [0, 1]."""
        query = l2_normalise(vector)
        best: dict[str, float] = {}
        for prototype in self._gallery.get(signal, []):
            if not prototype.is_valid(now):
                continue
            similarity = float(np.dot(query, prototype.vector))
            score = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
            if score > best.get(prototype.subject_id, 0.0):
                best[prototype.subject_id] = score
        return best

    def resolve(
        self,
        track_id: int,
        observations: Mapping[IdentitySignal, Vector],
        now: datetime,
        priors: Mapping[str, float] | None = None,
    ) -> IdentityAssignment:
        """Resolve one track observation into an identity assignment."""
        memory = self._tracks.setdefault(track_id, _TrackMemory())
        memory.observations += 1

        available: dict[IdentitySignal, dict[str, float]] = {}
        for signal, vector in observations.items():
            if signal not in self._weights:
                continue
            scores = self._signal_scores(signal, vector, now)
            if scores:
                available[signal] = scores
        if priors:
            prior_weight = self._weights.get(IdentitySignal.SPATIOTEMPORAL_PRIOR)
            if prior_weight is not None:
                available[IdentitySignal.SPATIOTEMPORAL_PRIOR] = {
                    sid: max(0.0, min(1.0, score)) for sid, score in priors.items()
                }

        if not available:
            return self._unknown(track_id, memory, ())

        # Renormalise over available weights: a missing signal must not simply subtract
        # confidence, otherwise every back-facing track would read as a stranger.
        weight_sum = sum(self._weights[s] for s in available)
        candidates: set[str] = {sid for scores in available.values() for sid in scores}
        fused: dict[str, float] = {}
        for subject_id in candidates:
            total = sum(
                self._weights[signal] * scores.get(subject_id, 0.0)
                for signal, scores in available.items()
            )
            fused[subject_id] = total / weight_sum if weight_sum else 0.0

        for subject_id, value in fused.items():
            previous = memory.scores.get(subject_id)
            memory.scores[subject_id] = (
                value
                if previous is None
                else (1 - self._EMA_ALPHA) * previous + self._EMA_ALPHA * value
            )

        best_id = max(memory.scores, key=lambda sid: memory.scores[sid])
        best_score = memory.scores[best_id]
        signal_scores = tuple(
            SignalScore(
                signal=signal,
                score=scores.get(best_id, 0.0),
                weight=self._weights[signal],
            )
            for signal, scores in sorted(available.items(), key=lambda kv: kv[0].value)
        )

        if best_score < self._config.accept_threshold:
            # Below accept but above reject: hold any previous assignment rather than
            # flip-flopping, but never invent a new one.
            if (
                memory.assigned_subject_id is not None
                and best_score >= self._config.reject_threshold
            ):
                memory.frames_of_agreement += 1
                return IdentityAssignment(
                    subject_id=memory.assigned_subject_id,
                    kind=memory.assigned_kind,
                    confidence=best_score,
                    signal_scores=signal_scores,
                    frames_of_agreement=memory.frames_of_agreement,
                )
            return self._unknown(track_id, memory, signal_scores)

        if memory.assigned_subject_id in (None, best_id):
            memory.assigned_subject_id = best_id
            memory.assigned_kind = SubjectKind.RESIDENT
            memory.frames_of_agreement += 1
            memory.challenger_subject_id = None
            memory.challenger_frames = 0
        else:
            # Hysteresis: an established identity only yields after sustained disagreement.
            if memory.challenger_subject_id == best_id:
                memory.challenger_frames += 1
            else:
                memory.challenger_subject_id = best_id
                memory.challenger_frames = 1
            if memory.challenger_frames >= self._config.hysteresis_frames:
                memory.assigned_subject_id = best_id
                memory.assigned_kind = SubjectKind.RESIDENT
                memory.frames_of_agreement = memory.challenger_frames
                memory.challenger_subject_id = None
                memory.challenger_frames = 0
            else:
                return IdentityAssignment(
                    subject_id=memory.assigned_subject_id,
                    kind=memory.assigned_kind,
                    confidence=memory.scores.get(memory.assigned_subject_id, best_score),
                    signal_scores=signal_scores,
                    frames_of_agreement=memory.frames_of_agreement,
                )

        return IdentityAssignment(
            subject_id=best_id,
            kind=SubjectKind.RESIDENT,
            confidence=best_score,
            signal_scores=signal_scores,
            frames_of_agreement=memory.frames_of_agreement,
        )

    def _unknown(
        self,
        track_id: int,
        memory: _TrackMemory,
        signal_scores: Sequence[SignalScore],
    ) -> IdentityAssignment:
        """Assign an ephemeral id. Visitors are never enrolled into the gallery."""
        subject_id = self._visitor_ids.setdefault(track_id, f"visitor:{uuid.uuid4().hex[:12]}")
        best = max((s.score for s in signal_scores), default=0.0)
        return IdentityAssignment(
            subject_id=subject_id,
            kind=SubjectKind.UNKNOWN,
            confidence=best,
            signal_scores=tuple(signal_scores),
            frames_of_agreement=memory.frames_of_agreement,
        )

    def forget_track(self, track_id: int) -> None:
        self._tracks.pop(track_id, None)
        self._visitor_ids.pop(track_id, None)

    @property
    def gallery_size(self) -> int:
        return sum(len(bucket) for bucket in self._gallery.values())
