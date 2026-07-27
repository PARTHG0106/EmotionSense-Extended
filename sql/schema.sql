-- Well-being monitoring schema.
--
-- Two structural decisions carry the privacy posture:
--   1. Identity data (embeddings, names) lives in its own schema, separate from event data.
--      Behaviour analysis joins on an opaque resident_id and never needs the identity schema.
--   2. Raw frames are never a column anywhere. Only short retained clips are referenced,
--      by path, in media.clip, with a hard expiry.

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS events;
CREATE SCHEMA IF NOT EXISTS media;
CREATE SCHEMA IF NOT EXISTS audit;

-- =============================================================== identity schema
CREATE TABLE identity.resident (
    resident_id      TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    room             TEXT,
    consent_status   TEXT NOT NULL DEFAULT 'pending'
        CHECK (consent_status IN ('pending', 'granted', 'withdrawn')),
    consent_recorded_at TIMESTAMPTZ,
    enrolled_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    active           BOOLEAN NOT NULL DEFAULT TRUE
);

-- Gallery prototypes. Body/appearance vectors expire; face vectors are long-lived.
CREATE TABLE identity.prototype (
    prototype_id     BIGSERIAL PRIMARY KEY,
    resident_id      TEXT NOT NULL REFERENCES identity.resident(resident_id) ON DELETE CASCADE,
    signal           TEXT NOT NULL
        CHECK (signal IN ('body', 'face', 'gait', 'anthropometry')),
    embedding        BYTEA NOT NULL,
    dim              SMALLINT NOT NULL,
    quality          REAL NOT NULL CHECK (quality BETWEEN 0 AND 1),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ,
    CONSTRAINT ephemeral_signals_must_expire
        CHECK (signal NOT IN ('body', 'anthropometry') OR expires_at IS NOT NULL)
);
CREATE INDEX prototype_resident_signal_idx
    ON identity.prototype (resident_id, signal, expires_at);

-- Visitors are never enrolled into the gallery. Session rows are purged on a timer.
CREATE TABLE identity.visitor_session (
    visitor_id       TEXT PRIMARY KEY,
    first_seen       TIMESTAMPTZ NOT NULL,
    last_seen        TIMESTAMPTZ NOT NULL,
    purge_after      TIMESTAMPTZ NOT NULL
);

-- ================================================================= events schema
CREATE TABLE events.camera (
    camera_id        TEXT PRIMARY KEY,
    zone             TEXT NOT NULL,
    resolution       TEXT,
    fps_target       SMALLINT,
    active           BOOLEAN NOT NULL DEFAULT TRUE
);

-- Monthly partitions: events are the largest table and are retained 365 days, so
-- expiry is a partition drop rather than a mass DELETE.
CREATE TABLE events.activity_event (
    event_id             TEXT NOT NULL,
    subject_id           TEXT NOT NULL,
    subject_kind         TEXT NOT NULL CHECK (subject_kind IN ('resident', 'visitor', 'unknown')),
    camera_id            TEXT NOT NULL,
    zone                 TEXT,
    label                TEXT NOT NULL,
    started_at           TIMESTAMPTZ NOT NULL,
    ended_at             TIMESTAMPTZ NOT NULL,
    confidence           REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    identity_confidence  REAL NOT NULL CHECK (identity_confidence BETWEEN 0 AND 1),
    source               TEXT NOT NULL
        CHECK (source IN ('pose_rule', 'video_model', 'fusion', 'sensor')),
    evidence             JSONB NOT NULL,
    model_versions       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, started_at),
    CONSTRAINT window_ordered CHECK (ended_at >= started_at),
    -- An event that cannot cite its evidence cannot be explained, so it is rejected.
    CONSTRAINT evidence_present CHECK (jsonb_array_length(evidence) > 0)
) PARTITION BY RANGE (started_at);

CREATE INDEX activity_event_subject_time_idx
    ON events.activity_event (subject_id, started_at DESC);
CREATE INDEX activity_event_label_idx ON events.activity_event (label, started_at DESC);

CREATE TABLE events.activity_event_2026_03 PARTITION OF events.activity_event
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE events.activity_event_2026_04 PARTITION OF events.activity_event
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE TABLE events.fall_assessment (
    assessment_id        BIGSERIAL PRIMARY KEY,
    event_id             TEXT NOT NULL,
    detected             BOOLEAN NOT NULL,
    confidence           REAL NOT NULL,
    rules_fired          TEXT[] NOT NULL,
    drop_ratio           REAL,
    drop_seconds         REAL,
    horizontal_hold_seconds REAL,
    stillness_seconds    REAL,
    self_recovered       BOOLEAN NOT NULL DEFAULT FALSE,
    reason               TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Aggregates. completeness is mandatory: a partial day must never be read as a quiet day.
CREATE TABLE events.daily_feature (
    subject_id       TEXT NOT NULL,
    day              DATE NOT NULL,
    bucket           TEXT NOT NULL CHECK (bucket IN ('night', 'morning', 'afternoon', 'evening')),
    features         JSONB NOT NULL,
    completeness     REAL NOT NULL CHECK (completeness BETWEEN 0 AND 1),
    computed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, day, bucket)
);

CREATE TABLE events.baseline (
    subject_id       TEXT NOT NULL,
    metric           TEXT NOT NULL,
    bucket           TEXT NOT NULL,
    day_type         TEXT NOT NULL CHECK (day_type IN ('weekday', 'weekend')),
    median           DOUBLE PRECISION NOT NULL,
    mad              DOUBLE PRECISION NOT NULL,
    n_days           SMALLINT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('forming', 'stable', 'drifting')),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subject_id, metric, bucket, day_type)
);

CREATE TABLE events.anomaly_signal (
    anomaly_id       TEXT PRIMARY KEY,
    subject_id       TEXT NOT NULL,
    metric           TEXT NOT NULL,
    bucket           TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    ended_at         TIMESTAMPTZ NOT NULL,
    observed         DOUBLE PRECISION NOT NULL,
    baseline_median  DOUBLE PRECISION NOT NULL,
    deviation_sigma  DOUBLE PRECISION NOT NULL,
    score            REAL NOT NULL,
    method           TEXT NOT NULL,
    severity         TEXT NOT NULL,
    evidence_event_ids TEXT[] NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE events.alert (
    alert_id             TEXT PRIMARY KEY,
    subject_id           TEXT NOT NULL,
    ts                   TIMESTAMPTZ NOT NULL,
    severity             TEXT NOT NULL
        CHECK (severity IN ('normal', 'attention', 'warning', 'critical')),
    kind                 TEXT NOT NULL,
    -- The six explanation fields are columns, not free text, so completeness is enforceable.
    exp_what             TEXT NOT NULL,
    exp_when             TEXT NOT NULL,
    exp_why_flagged      TEXT NOT NULL,
    exp_baseline_delta   TEXT NOT NULL,
    exp_confidence       TEXT NOT NULL,
    exp_check_next       TEXT NOT NULL,
    prose                TEXT,
    confidence           REAL NOT NULL,
    evidence_event_ids   TEXT[] NOT NULL DEFAULT '{}',
    anomaly_ids          TEXT[] NOT NULL DEFAULT '{}',
    requires_human_review BOOLEAN NOT NULL,
    -- Non-null means the alert was computed but deliberately not shown. Kept for
    -- suppression auditing: silent alerts must be reviewable.
    suppressed_reason    TEXT,
    model_versions       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT explanation_complete CHECK (
        length(trim(exp_what)) > 0 AND length(trim(exp_when)) > 0
        AND length(trim(exp_why_flagged)) > 0 AND length(trim(exp_baseline_delta)) > 0
        AND length(trim(exp_confidence)) > 0 AND length(trim(exp_check_next)) > 0
    )
);
CREATE INDEX alert_open_idx ON events.alert (subject_id, ts DESC)
    WHERE suppressed_reason IS NULL;

-- Caregiver feedback. was_true_positive is the only ground truth a deployment produces
-- and is what per-resident threshold recalibration reads.
CREATE TABLE events.alert_feedback (
    feedback_id        BIGSERIAL PRIMARY KEY,
    alert_id           TEXT NOT NULL REFERENCES events.alert(alert_id) ON DELETE CASCADE,
    actor_id           TEXT NOT NULL,
    acknowledged_at    TIMESTAMPTZ,
    resolved_at        TIMESTAMPTZ,
    outcome            TEXT,
    was_true_positive  BOOLEAN,
    note               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE events.caregiver_note (
    note_id          BIGSERIAL PRIMARY KEY,
    subject_id       TEXT NOT NULL,
    actor_id         TEXT NOT NULL,
    body             TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ================================================================== media schema
CREATE TABLE media.clip (
    clip_id          TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL,
    storage_path     TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL,
    duration_seconds REAL NOT NULL,
    -- Hard expiry. A retention job deletes the object and the row together.
    expires_at       TIMESTAMPTZ NOT NULL,
    redacted         BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX clip_expiry_idx ON media.clip (expires_at);

-- ================================================================== audit schema
-- Append-only by convention and by grant: the application role has INSERT and SELECT only.
CREATE TABLE audit.access_log (
    log_id           BIGSERIAL PRIMARY KEY,
    ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id         TEXT NOT NULL,
    actor_role       TEXT NOT NULL,
    action           TEXT NOT NULL,
    resident_id      TEXT,
    target           TEXT,
    purpose          TEXT NOT NULL,
    ip_address       INET
);
CREATE INDEX access_log_resident_idx ON audit.access_log (resident_id, ts DESC);

CREATE RULE audit_no_update AS ON UPDATE TO audit.access_log DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit.access_log DO INSTEAD NOTHING;
