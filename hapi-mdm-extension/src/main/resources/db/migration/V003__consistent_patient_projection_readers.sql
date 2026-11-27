BEGIN;
SET LOCAL lock_timeout = '5s';
DO $install$
BEGIN
    PERFORM set_config('search_path', format('%I, pg_catalog', current_schema()), true);
    PERFORM omni_projection_check_publisher();
    IF to_regclass('omni_projection_reader_generation') IS NOT NULL THEN
        RAISE EXCEPTION 'Reader migration already installed; no implicit upgrade or reset';
    END IF;
    IF EXISTS (
        SELECT 1 FROM omni_projection_event WHERE classification = 'unresolved'
        UNION ALL
        SELECT 1 FROM omni_projection_job WHERE state <> 'acknowledged'
    ) THEN
        RAISE EXCEPTION 'Reader publication requires a fully drained, resolved projection';
    END IF;
    IF to_regclass('hfj_search') IS NULL THEN
        RAISE EXCEPTION 'HAPI search-cache contract is unavailable';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_attribute
        WHERE attrelid = to_regclass('hfj_search') AND attname IN ('search_uuid', 'search_deleted')
        GROUP BY attrelid HAVING count(*) = 2
    ) THEN
        RAISE EXCEPTION 'HAPI search-cache contract is unavailable';
    END IF;
    IF to_regclass('bt2_job_instance') IS NULL THEN
        RAISE EXCEPTION 'HAPI Batch2 export contract is unavailable';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_attribute
        WHERE attrelid = to_regclass('bt2_job_instance')
            AND attname IN ('id', 'definition_id', 'report', 'report_vc')
        GROUP BY attrelid HAVING count(*) = 4
    ) THEN
        RAISE EXCEPTION 'HAPI Batch2 export contract is unavailable';
    END IF;
    LOCK TABLE omni_projection_event, omni_projection_job, hfj_search, bt2_job_instance
        IN ACCESS EXCLUSIVE MODE;
END
$install$;

CREATE TABLE omni_projection_reader_generation (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    generation bigint NOT NULL CHECK (generation >= 0),
    published_generation bigint NOT NULL CHECK (
        published_generation >= 0 AND published_generation <= generation
    ),
    last_transaction xid8
);
INSERT INTO omni_projection_reader_generation(singleton, generation, published_generation)
VALUES (true, 0, 0);

CREATE TABLE omni_projection_legacy_export_job (
    job_id text PRIMARY KEY
);
CREATE TABLE omni_projection_legacy_export_binary (
    binary_id text PRIMARY KEY,
    job_id text NOT NULL REFERENCES omni_projection_legacy_export_job(job_id)
);

INSERT INTO omni_projection_legacy_export_job(job_id)
SELECT id::text FROM bt2_job_instance WHERE definition_id = 'BULK_EXPORT';

INSERT INTO omni_projection_legacy_export_binary(binary_id, job_id)
SELECT DISTINCT output.binary_id, job.id::text
FROM bt2_job_instance job
CROSS JOIN LATERAL (
    SELECT coalesce(
        nullif(job.report_vc, ''),
        CASE WHEN job.report IS NOT NULL THEN convert_from(lo_get(job.report), 'UTF8') ELSE NULL END
    ) AS report_json
) stored_report
CROSS JOIN LATERAL jsonb_each(
    coalesce(
        CASE WHEN job.definition_id = 'BULK_EXPORT' AND stored_report.report_json IS NOT NULL
            THEN coalesce(
                stored_report.report_json::jsonb -> 'resourceTypeToBinaryIds',
                stored_report.report_json::jsonb -> 'resourceType2BinaryIds'
            )
            ELSE NULL
        END,
        '{}'::jsonb
    )
) resource_output
CROSS JOIN LATERAL jsonb_array_elements_text(resource_output.value) output(binary_id);

CREATE TRIGGER omni_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
    ON omni_projection_legacy_export_job EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_legacy_export_job ENABLE ALWAYS TRIGGER omni_projection_immutable;
CREATE TRIGGER omni_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
    ON omni_projection_legacy_export_binary EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_legacy_export_binary ENABLE ALWAYS TRIGGER omni_projection_immutable;
CREATE TRIGGER omni_projection_immutable BEFORE DELETE OR TRUNCATE
    ON omni_projection_reader_generation EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_reader_generation ENABLE ALWAYS TRIGGER omni_projection_immutable;

CREATE FUNCTION omni_projection_acquire_reader_lock() RETURNS bigint
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    current_generation bigint;
BEGIN
    PERFORM pg_advisory_xact_lock_shared(1330462281, 1296323889);
    SELECT generation INTO current_generation
    FROM omni_projection_reader_generation WHERE singleton;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Patient reader generation is unavailable' USING ERRCODE = '55000';
    END IF;
    RETURN current_generation;
END
$$;

CREATE FUNCTION omni_projection_invalidate_patient_searches() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(1330462281, 1296323889);
    UPDATE omni_projection_reader_generation
    SET generation = generation + 1, last_transaction = pg_current_xact_id()
    WHERE singleton AND last_transaction IS DISTINCT FROM pg_current_xact_id();

    IF FOUND THEN
        UPDATE hfj_search SET search_deleted = true
        WHERE search_deleted IS DISTINCT FROM true;
    END IF;
    RETURN NEW;
END
$$;
CREATE TRIGGER omni_projection_reader_invalidate
    BEFORE INSERT ON omni_projection_event
    FOR EACH ROW EXECUTE FUNCTION omni_projection_invalidate_patient_searches();
ALTER TABLE omni_projection_event ENABLE ALWAYS TRIGGER omni_projection_reader_invalidate;

ALTER FUNCTION omni_projection_complete(bigint, uuid, bigint, integer, integer)
    RENAME TO omni_projection_complete_v2;
CREATE FUNCTION omni_projection_complete(
    event bigint, worker uuid, token bigint, updates integer, goldens integer
) RETURNS void LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(1330462281, 1296323889);
    PERFORM omni_projection_complete_v2(event, worker, token, updates, goldens);
    IF NOT EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved')
        AND NOT EXISTS (SELECT FROM omni_projection_job WHERE state <> 'acknowledged') THEN
        UPDATE omni_projection_reader_generation
        SET published_generation = generation
        WHERE singleton;
    END IF;
END
$$;

CREATE FUNCTION omni_projection_is_legacy_export_job(requested_job_id text) RETURNS boolean
LANGUAGE sql STABLE SET search_path FROM CURRENT AS $$
    SELECT EXISTS (
        SELECT FROM omni_projection_legacy_export_job WHERE job_id = requested_job_id
    )
$$;
CREATE FUNCTION omni_projection_is_legacy_export_binary(requested_binary_id text) RETURNS boolean
LANGUAGE sql STABLE SET search_path FROM CURRENT AS $$
    SELECT EXISTS (
        SELECT FROM omni_projection_legacy_export_binary WHERE binary_id = requested_binary_id
    )
$$;

CREATE FUNCTION omni_projection_check_reader_protocol() RETURNS void
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM omni_projection_check_publisher();
    IF NOT EXISTS (
        SELECT FROM omni_projection_reader_generation
        WHERE singleton AND published_generation <= generation
    ) OR NOT EXISTS (
        SELECT FROM pg_trigger
        WHERE tgrelid = 'omni_projection_event'::regclass
            AND tgname = 'omni_projection_reader_invalidate'
            AND tgenabled = 'A' AND tgtype = 7 AND tgqual IS NULL AND tgnargs = 0
            AND tgfoid = 'omni_projection_invalidate_patient_searches()'::regprocedure
    ) OR NOT EXISTS (
        SELECT FROM pg_attribute
        WHERE attrelid = to_regclass('hfj_search')
            AND attname = 'search_deleted' AND NOT attisdropped
    ) THEN
        RAISE EXCEPTION 'Patient reader publication protocol is unavailable' USING ERRCODE = '55000';
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION omni_patient_projection_read_status() RETURNS text
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    current_generation bigint;
    published_generation bigint;
BEGIN
    PERFORM omni_projection_acquire_reader_lock();
    PERFORM omni_projection_check_reader_protocol();
    IF EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved') THEN
        RETURN 'BLOCKED_UNRESOLVED_CAPTURE';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_job WHERE state = 'exhausted') THEN
        RETURN 'BLOCKED_RETRY_EXHAUSTED';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_job WHERE state <> 'acknowledged') THEN
        RETURN 'BLOCKED_PROJECTION_PENDING';
    END IF;
    SELECT generation, omni_projection_reader_generation.published_generation
    INTO current_generation, published_generation
    FROM omni_projection_reader_generation WHERE singleton;
    IF current_generation IS DISTINCT FROM published_generation THEN
        RETURN 'BLOCKED_PROJECTION_PENDING';
    END IF;
    RETURN 'READY';
END
$$;

UPDATE hfj_search SET search_deleted = true WHERE search_deleted IS DISTINCT FROM true;
SELECT omni_projection_check_reader_protocol();
COMMIT;
