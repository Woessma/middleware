BEGIN;
SET LOCAL lock_timeout = '5s';
DO $install$
BEGIN
    PERFORM set_config('search_path', format('%I, pg_catalog', current_schema()), true);
    PERFORM omni_projection_check_contract();
    IF to_regclass('omni_projection_publisher') IS NOT NULL THEN
        RAISE EXCEPTION 'Projector migration already installed; no implicit upgrade or reset';
    END IF;
    LOCK TABLE omni_projection_event, omni_projection_job IN ACCESS EXCLUSIVE MODE;
END
$install$;

CREATE TABLE omni_projection_publisher (
    version integer PRIMARY KEY CHECK (version = 2),
    stage text NOT NULL CHECK (stage = 'PROJECTOR_NOT_PUBLISHED')
);
INSERT INTO omni_projection_publisher VALUES (2, 'PROJECTOR_NOT_PUBLISHED');
CREATE TRIGGER omni_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON omni_projection_publisher
    EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_publisher ENABLE ALWAYS TRIGGER omni_projection_immutable;

ALTER TABLE omni_projection_job
    ADD COLUMN acknowledged_at timestamptz,
    DROP CONSTRAINT omni_projection_job_state_check,
    DROP CONSTRAINT omni_projection_job_check,
    ADD CONSTRAINT omni_projection_job_state_check
        CHECK (state IN ('pending', 'leased', 'retry', 'exhausted', 'acknowledged')),
    ADD CONSTRAINT omni_projection_job_ownership_check CHECK (
        (state = 'leased' AND owner IS NOT NULL AND lease_until IS NOT NULL AND acknowledged_at IS NULL)
        OR (state = 'acknowledged' AND owner IS NOT NULL AND lease_until IS NULL AND acknowledged_at IS NOT NULL)
        OR (state IN ('pending', 'retry', 'exhausted')
            AND owner IS NULL AND lease_until IS NULL AND acknowledged_at IS NULL)
    );

CREATE TABLE omni_projection_receipt (
    event_id bigint PRIMARY KEY REFERENCES omni_projection_job,
    owner uuid NOT NULL,
    fence bigint NOT NULL CHECK (fence > 0),
    transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    golden_updates integer NOT NULL CHECK (golden_updates >= 0),
    golden_count integer NOT NULL CHECK (golden_count >= golden_updates)
);
CREATE TRIGGER omni_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON omni_projection_receipt
    EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_receipt ENABLE ALWAYS TRIGGER omni_projection_immutable;

CREATE FUNCTION omni_projection_check_publisher() RETURNS void
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    name text;
BEGIN
    PERFORM omni_projection_check_contract();
    IF NOT EXISTS (
        SELECT FROM omni_projection_publisher WHERE version = 2 AND stage = 'PROJECTOR_NOT_PUBLISHED'
    ) OR EXISTS (
        SELECT FROM omni_projection_job j LEFT JOIN omni_projection_receipt r USING (event_id)
        WHERE (j.state = 'acknowledged') IS DISTINCT FROM (r.event_id IS NOT NULL)
            OR (r.event_id IS NOT NULL AND (j.owner IS DISTINCT FROM r.owner OR j.fence <> r.fence))
    ) THEN
        RAISE EXCEPTION 'Patient projector completion contract is unavailable' USING ERRCODE = '55000';
    END IF;
    FOREACH name IN ARRAY ARRAY['omni_projection_publisher', 'omni_projection_receipt'] LOOP
        IF NOT EXISTS (
            SELECT FROM pg_trigger WHERE tgrelid = to_regclass(name)
                AND tgname = 'omni_projection_immutable' AND tgenabled = 'A'
                AND tgtype = 58 AND tgqual IS NULL AND tgnargs = 0
                AND tgfoid = 'omni_projection_deny_rewrite()'::regprocedure
        ) THEN
            RAISE EXCEPTION 'Patient projector receipt protection is unavailable' USING ERRCODE = '55000';
        END IF;
    END LOOP;
END
$$;

CREATE FUNCTION omni_projection_lock_inputs() RETURNS void
LANGUAGE plpgsql SET search_path FROM CURRENT SET lock_timeout = '2s' AS $$
BEGIN
    LOCK TABLE hfj_history_tag, hfj_res_tag, hfj_res_ver, hfj_res_ver_prov,
        hfj_resource, hfj_tag_def, mpi_link IN SHARE ROW EXCLUSIVE MODE;
END
$$;

CREATE FUNCTION omni_projection_require_input_locks() RETURNS void
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF EXISTS (
        SELECT FROM omni_projection_coverage k WHERE NOT EXISTS (
            SELECT FROM pg_locks l WHERE l.pid = pg_backend_pid() AND l.granted
                AND l.locktype = 'relation' AND l.relation = to_regclass(k.table_name)
                AND l.mode IN ('ShareRowExclusiveLock', 'ExclusiveLock', 'AccessExclusiveLock')
        )
    ) THEN
        RAISE EXCEPTION 'Patient projection requires all input locks in the same transaction'
            USING ERRCODE = '55000';
    END IF;
END
$$;

ALTER FUNCTION omni_projection_claim(uuid, integer) RENAME TO omni_projection_capture_claim;
CREATE FUNCTION omni_projection_claim(worker uuid, lease_ms integer)
RETURNS TABLE (event_id bigint, fence bigint, attempts integer)
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM omni_projection_check_publisher();
    RETURN QUERY SELECT * FROM omni_projection_capture_claim(worker, lease_ms);
END
$$;

CREATE FUNCTION omni_projection_complete(
    event bigint, worker uuid, token bigint, updates integer, goldens integer
) RETURNS void LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    job omni_projection_job;
BEGIN
    PERFORM omni_projection_require_input_locks();
    PERFORM omni_projection_check_publisher();
    IF event IS NULL OR worker IS NULL OR token IS NULL OR updates IS NULL OR goldens IS NULL
        OR updates < 0 OR goldens < updates THEN
        RAISE EXCEPTION 'Invalid Patient projection completion' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved') THEN
        RAISE EXCEPTION 'Unresolved Patient capture requires review' USING ERRCODE = '55000';
    END IF;
    SELECT * INTO job FROM omni_projection_job WHERE event_id = event FOR UPDATE;
    IF NOT FOUND OR job.state <> 'leased' OR job.owner IS DISTINCT FROM worker
        OR job.fence IS DISTINCT FROM token OR job.lease_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'Stale Patient projection completion' USING ERRCODE = '55000';
    END IF;
    INSERT INTO omni_projection_receipt (event_id, owner, fence, golden_updates, golden_count)
        VALUES (event, worker, token, updates, goldens);
    UPDATE omni_projection_job SET state = 'acknowledged', lease_until = NULL,
        acknowledged_at = clock_timestamp(), failure_code = NULL
    WHERE event_id = event AND lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Patient projection lease expired before completion' USING ERRCODE = '55000';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION omni_patient_projection_read_status() RETURNS text
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM omni_projection_check_publisher();
    IF EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved') THEN
        RETURN 'BLOCKED_UNRESOLVED_CAPTURE';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_job WHERE state = 'exhausted') THEN
        RETURN 'BLOCKED_RETRY_EXHAUSTED';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_job WHERE state <> 'acknowledged') THEN
        RETURN 'BLOCKED_PROJECTION_PENDING';
    END IF;
    RETURN 'BLOCKED_READER_NOT_PUBLISHED';
END
$$;
SELECT omni_projection_check_publisher();
COMMIT;
