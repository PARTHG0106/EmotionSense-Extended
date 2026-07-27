-- Retention jobs. Run nightly; each is idempotent.
--
-- Retention is enforced in the database rather than in application code, because a
-- privacy guarantee that depends on a service staying healthy is not a guarantee.

-- 1. Expire appearance prototypes (clothing changes daily; these are not identity).
DELETE FROM identity.prototype
WHERE expires_at IS NOT NULL AND expires_at < now();

-- 2. Purge visitor sessions. Visitors did not consent to longitudinal tracking.
DELETE FROM identity.visitor_session WHERE purge_after < now();

-- 3. Delete expired clips. Storage objects are removed by the same job before this runs.
DELETE FROM media.clip WHERE expires_at < now();

-- 4. Drop event partitions older than 365 days (aggregates in events.daily_feature
--    survive for 730 days, so long-term trends outlive raw event rows).
--    Example, run by the scheduler with the computed partition name:
--    DROP TABLE IF EXISTS events.activity_event_2025_03;

-- 5. Expire aggregates beyond 730 days.
DELETE FROM events.daily_feature WHERE day < (current_date - INTERVAL '730 days');

-- Audit rows are never deleted by this job.
