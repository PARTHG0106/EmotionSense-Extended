# 07 - Database schema

Canonical DDL lives in [`sql/schema.sql`](../sql/schema.sql). Design summary and the
reasoning behind the non-obvious choices:

## Separation of identity from events

Four schemas with separate grants:

- `identity` (restricted): residents, consent records, encrypted biometric galleries.
- `events` (pseudonymous): activity events, daily features, baselines, anomalies, alerts,
  caregiver notes. Holds `subject_id` only - never a name.
- `media` (transient): incident clips with a mandatory `expires_at`.
- `audit` (append-only): access log, with `UPDATE`/`DELETE` revoked.

Most services can read `events` and cannot read `identity`. Deleting a resident cascades
their biometrics, after which their pseudonymous events can be purged by `subject_id` in a
single statement.

## Choices worth defending

| Choice | Reason |
| --- | --- |
| `events.activity_event` partitioned monthly by `ts_start` | retention becomes a partition drop, not a mass delete |
| `alert.suppressed_reason` | records alerts that *almost* fired; without it, post-incident "why did we miss this?" is unanswerable |
| `daily_feature.completeness` | prevents a camera outage being read as "resident was inactive all day" |
| `baseline` keyed by (subject, metric, bucket, daytype) with `median`/`mad` | robust statistics per time-of-day and weekday/weekend; one hospital day cannot reshape a baseline |
| `model_versions` JSONB on every event | any alert can be reproduced against the exact models that produced it |
| `biometric_gallery.expires_at` | body-appearance prototypes decay within ~36 h because clothing changes daily; face and gait prototypes do not expire |
| `visitor.transient` | visitors have not consented; ephemeral ids, purged nightly, never enrolled |
