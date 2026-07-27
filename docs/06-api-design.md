# 06 - API design

FastAPI. OIDC bearer auth, RBAC scopes (`caregiver`, `nurse`, `admin`, `family_limited`),
per-resident row-level authorization, and an audit row on every identity or media access.

## Residents and identity

```
GET    /v1/residents                        list + current status summary
GET    /v1/residents/{id}                   profile, care notes, enrolled signals
POST   /v1/residents/{id}/enroll            enrollment media -> gallery build
DELETE /v1/residents/{id}/biometrics        erase all embeddings (right to erasure)
GET    /v1/residents/{id}/identity-health   gallery size, last match confidence, drift
```

## Live state

```
GET  /v1/residents/{id}/status   activity, zone, posture, identity confidence,
                                 wellbeing score, risk level
WS   /v1/ws/live?resident_id=    status deltas, new events, new alerts
```

## Events and timeline

```
GET  /v1/events?resident_id&from&to&label&min_confidence&zone&page
GET  /v1/events/{event_id}                  event + evidence + optional clip token
GET  /v1/residents/{id}/timeline?date=      bucketed day timeline for rendering
```

## Alerts

```
GET  /v1/alerts?severity&status&resident_id
GET  /v1/alerts/{id}                        six-field explanation + evidence chain
POST /v1/alerts/{id}/acknowledge            {caregiver_id, note}
POST /v1/alerts/{id}/resolve                {outcome, was_true_positive, note}
```

`was_true_positive` is the most valuable field in the system: it is the only ground truth a
deployment will ever produce, and per-resident threshold recalibration depends on it. It
must be a one-tap action in the UI.

## Behaviour and reports

```
GET  /v1/residents/{id}/behavior/baseline
GET  /v1/residents/{id}/behavior/trends?metric=gait_speed&window=28d
GET  /v1/residents/{id}/reports/daily?date=
GET  /v1/residents/{id}/reports/weekly?week=
POST /v1/residents/{id}/reports/generate    idempotent; returns cached if present
```

## Grounded caregiver Q&A

```
POST /v1/residents/{id}/ask
  { "question": "Has she been sleeping less this week?" }
  -> { answer, cited_event_ids[], cited_metrics[], confidence, unanswerable_reason? }
```

Retrieval runs over structured aggregates and events only. If the question cannot be
answered from stored structured data, the endpoint returns `unanswerable_reason` rather
than speculating.

## Ops

```
GET /v1/health    per-camera FPS, model versions, queue depth, degradation state
GET /v1/audit     append-only access log query (admin only)
```
