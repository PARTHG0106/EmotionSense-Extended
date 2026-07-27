# 10 - Privacy and safety

This system watches vulnerable people in their homes. Privacy is an architectural
constraint, not a settings page.

## Data minimization

| Data | Policy |
| --- | --- |
| Raw video frames | In-memory only; never written to disk in normal operation |
| Incident clips | Only on a confirmed critical alert or consented review; encrypted, 72 h TTL, audited, auto-purged |
| Pose keypoints | 30 days (needed to debug falls and ADL), then aggregated away |
| Activity events | 12 months - this is the clinical value |
| Daily aggregates | 24 months |
| Biometric embeddings | Encrypted at rest, key in KMS/HSM, never leave the site boundary, deletable on request |
| Audio | Feature level only (voice activity, impact sounds). Never store raw audio; never transcribe conversation content by default |

## Access control

OIDC SSO; RBAC (`caregiver`, `nurse`, `admin`, `family_limited`); per-resident row-level
authorization. `family_limited` sees daily summaries and alerts only - never live state,
never clips. Every identity or media access writes an append-only audit row with actor and
purpose. Exporting a clip off-site requires two people.

## Consent and dignity

- Written consent from the resident or legal proxy, stored as a structured record with
  scope and date. Withdrawal is one action that halts processing and purges biometrics.
- **No cameras in bathrooms or the bed area** without separate explicit consent; prefer
  non-camera sensing (bed pressure, door contacts, radar) for those zones.
- Physical signage at every monitored entrance.
- Visitors are transient by default: ephemeral id, no gallery enrollment, purged nightly.
  Visitors have not consented and must not be profiled.

## Safety rules encoded in software, not policy PDFs

1. `requires_human_review = true` on every warning and critical alert; the system cannot
   self-close them.
2. No diagnostic vocabulary in generated output. A banned-phrase check runs before any text
   reaches a caregiver; a violation downgrades the alert to its structured card.
3. Low-confidence path: if identity confidence is below the configured floor, or camera
   health is degraded, behavioural claims are suppressed and the UI states why. Silence
   with a reason beats a confident guess.
4. Fall alerts are never rate-limited. Anomaly alerts are capped at 3 per resident per day
   to prevent alert fatigue.
5. Camera outage or model failure raises an **ops alert**, never a behavioural inference.
   "No data" and "no activity" must never be conflated.
6. Any health-related statement is framed as an observation or risk signal, never a
   diagnosis.
