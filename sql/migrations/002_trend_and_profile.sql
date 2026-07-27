-- Migration 002: persist behaviour trends and rolled-up profiles.
--
-- These two tables were missing from the initial schema. `sql/schema.sql` stores daily
-- features, baselines, anomalies and alerts, but the L3 outputs `TrendResult` and
-- `BehaviorProfile` had nowhere to live, which meant the weekly report had to be recomputed
-- from scratch on every request and a trend shown to a caregiver could not be reproduced
-- later. Both are needed for the report endpoints to be auditable.

CREATE TABLE IF NOT EXISTS events.behavior_trend (
    subject_id       TEXT NOT NULL,
    metric           TEXT NOT NULL,
    computed_on      DATE NOT NULL,
    window_days      SMALLINT NOT NULL,
    direction        TEXT NOT NULL CHECK (direction IN ('improving', 'stable', 'declining')),
    slope_per_day    DOUBLE PRECISION NOT NULL,
    p_value          DOUBLE PRECISION NOT NULL CHECK (p_value BETWEEN 0 AND 1),
    n_points         SMALLINT NOT NULL,
    -- The caregiver-facing sentence is stored, not regenerated. Regenerating it later with a
    -- newer model would change what the record says was shown at the time.
    statement        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (subject_id, metric, computed_on)
);

CREATE INDEX IF NOT EXISTS behavior_trend_subject_idx
    ON events.behavior_trend (subject_id, computed_on DESC);

CREATE TABLE IF NOT EXISTS events.behavior_profile (
    subject_id       TEXT NOT NULL,
    generated_at     TIMESTAMPTZ NOT NULL,
    wellbeing_score  SMALLINT NOT NULL CHECK (wellbeing_score BETWEEN 0 AND 100),
    risk_level       TEXT NOT NULL CHECK (risk_level IN ('low', 'moderate', 'high')),
    -- Components are stored so the score can always be broken down and challenged. A score
    -- without its components is an unfalsifiable number in front of a caregiver.
    components       JSONB NOT NULL DEFAULT '{}'::jsonb,
    baseline_forming BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (subject_id, generated_at)
);

CREATE INDEX IF NOT EXISTS behavior_profile_latest_idx
    ON events.behavior_profile (subject_id, generated_at DESC);
