BEGIN;
SET LOCAL lock_timeout = '5s';

DO $install$
DECLARE
    schema_name text := current_schema();
    table_name text;
    expected record;
    primary_key text[];
BEGIN
    IF schema_name IS NULL OR schema_name IN ('pg_catalog', 'information_schema')
            OR current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Outbox installation requires an explicit HAPI schema and READ COMMITTED';
    END IF;
    PERFORM set_config('search_path', format('%I, pg_catalog', schema_name), true);
    IF to_regclass('omni_projection_migration') IS NOT NULL THEN
        RAISE EXCEPTION 'Projection migration already installed; no implicit reset or upgrade';
    END IF;
    FOREACH table_name IN ARRAY ARRAY[
        'hfj_history_tag', 'hfj_res_tag', 'hfj_res_ver', 'hfj_res_ver_prov',
        'hfj_resource', 'hfj_tag_def', 'mpi_link'
    ] LOOP
        IF NOT EXISTS (
            SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = schema_name AND c.relname = table_name
                AND c.relkind = 'r' AND c.relpersistence = 'p'
                AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity
                AND NOT EXISTS (
                    SELECT FROM pg_inherits WHERE inhparent = c.oid OR inhrelid = c.oid
                )
        ) THEN
            RAISE EXCEPTION 'Unsupported HAPI capture table: %', table_name;
        END IF;
        EXECUTE format('LOCK TABLE %I.%I IN ACCESS EXCLUSIVE MODE', schema_name, table_name);
    END LOOP;
    FOR expected IN SELECT * FROM (VALUES
        ('hfj_resource', 'res_id'), ('hfj_res_ver', 'pid'), ('hfj_res_tag', 'pid'),
        ('hfj_history_tag', 'pid'), ('hfj_tag_def', 'tag_id'),
        ('hfj_res_ver_prov', 'res_ver_pid'), ('mpi_link', 'pid')
    ) AS keys(table_name, column_name) LOOP
        SELECT array_agg(a.attname::text ORDER BY key.ordinality) INTO primary_key
        FROM pg_constraint c
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS key(attnum, ordinality)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = key.attnum
        WHERE c.conrelid = to_regclass(expected.table_name) AND c.contype = 'p';
        IF primary_key IS DISTINCT FROM ARRAY[expected.column_name]::text[] THEN
            RAISE EXCEPTION 'Unsupported HAPI primary key on %', expected.table_name;
        END IF;
    END LOOP;

    FOR expected IN SELECT * FROM (VALUES
        ('hfj_resource', 'res_id', 'int8'), ('hfj_resource', 'res_type', 'varchar'),
        ('hfj_resource', 'res_ver', 'int8'), ('hfj_resource', 'partition_id', 'int4'),
        ('hfj_res_ver', 'res_id', 'int8'), ('hfj_res_ver', 'res_type', 'varchar'),
        ('hfj_res_ver', 'res_encoding', 'varchar'), ('hfj_res_ver', 'partition_id', 'int4'),
        ('hfj_res_tag', 'res_id', 'int8'), ('hfj_res_tag', 'res_type', 'varchar'),
        ('hfj_res_tag', 'tag_id', 'int8'), ('hfj_res_tag', 'partition_id', 'int4'),
        ('hfj_history_tag', 'res_id', 'int8'), ('hfj_history_tag', 'res_type', 'varchar'),
        ('hfj_history_tag', 'tag_id', 'int8'), ('hfj_history_tag', 'partition_id', 'int4'),
        ('hfj_tag_def', 'tag_id', 'int8'), ('hfj_res_ver_prov', 'res_pid', 'int8'),
        ('hfj_res_ver_prov', 'partition_id', 'int4'), ('mpi_link', 'pid', 'int8'),
        ('mpi_link', 'golden_resource_pid', 'int8'), ('mpi_link', 'target_pid', 'int8'),
        ('mpi_link', 'person_pid', 'int8'), ('mpi_link', 'match_result', 'int4'),
        ('mpi_link', 'partition_id', 'int4'),
        ('mpi_link', 'golden_resource_partition_id', 'int4'),
        ('mpi_link', 'target_partition_id', 'int4'),
        ('mpi_link', 'person_partition_id', 'int4')
    ) AS columns(table_name, column_name, type_name) LOOP
        IF NOT EXISTS (
            SELECT FROM pg_attribute
            WHERE attrelid = to_regclass(expected.table_name)
                AND attname = expected.column_name AND attnum > 0 AND NOT attisdropped
                AND atttypid = to_regtype(expected.type_name)::oid
        ) THEN
            RAISE EXCEPTION 'Unsupported HAPI column %.%', expected.table_name, expected.column_name;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT FROM hfj_resource WHERE res_type = 'Patient' AND partition_id IS NOT NULL
    ) OR EXISTS (
        SELECT FROM hfj_res_ver WHERE res_type = 'Patient'
            AND (partition_id IS NOT NULL OR res_encoding NOT IN ('JSON', 'JSONC', 'DEL'))
    ) OR EXISTS (
        SELECT FROM mpi_link WHERE partition_id IS NOT NULL
            OR golden_resource_partition_id IS NOT NULL OR target_partition_id IS NOT NULL
            OR person_partition_id IS NOT NULL
    ) OR EXISTS (
        SELECT FROM hfj_res_tag WHERE res_type = 'Patient' AND partition_id IS NOT NULL
        UNION ALL
        SELECT FROM hfj_history_tag WHERE res_type = 'Patient' AND partition_id IS NOT NULL
    ) OR EXISTS (
        SELECT FROM hfj_res_ver_prov p JOIN hfj_resource r ON r.res_id = p.res_pid
        WHERE r.res_type = 'Patient' AND p.partition_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Patient partitions or external payload encodings are not supported';
    END IF;
END
$install$;

CREATE TABLE omni_projection_migration (
    version integer PRIMARY KEY CHECK (version = 1),
    hapi_version text NOT NULL CHECK (hapi_version = '8.12.0'),
    stage text NOT NULL CHECK (stage = 'CAPTURE_ONLY'),
    installed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE omni_projection_coverage (
    table_name text PRIMARY KEY,
    columns_signature text NOT NULL,
    primary_key_columns text[] NOT NULL
);
INSERT INTO omni_projection_coverage
SELECT c.relname, string_agg(
    a.attname || ':' || a.atttypid::text || ':' || a.attnotnull::text, ',' ORDER BY a.attnum
), ARRAY(
    SELECT a.attname::text FROM pg_constraint k
    CROSS JOIN LATERAL unnest(k.conkey) WITH ORDINALITY AS key(attnum, ordinality)
    JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = key.attnum
    WHERE k.conrelid = c.oid AND k.contype = 'p' ORDER BY key.ordinality
)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = current_schema() AND c.relname IN (
    'hfj_resource', 'hfj_res_ver', 'hfj_res_tag', 'hfj_history_tag',
    'hfj_tag_def', 'hfj_res_ver_prov', 'mpi_link'
)
GROUP BY c.oid, c.relname;

CREATE TABLE omni_projection_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    captured_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    table_name text REFERENCES omni_projection_coverage,
    operation text NOT NULL CHECK (operation IN ('BOOTSTRAP', 'INSERT', 'UPDATE', 'DELETE')),
    classification text NOT NULL CHECK (classification IN ('patient', 'unresolved')),
    affected_pids bigint[] NOT NULL,
    old_metadata jsonb,
    new_metadata jsonb,
    CHECK (array_position(affected_pids, NULL) IS NULL),
    CHECK (
        (operation = 'BOOTSTRAP' AND table_name IS NULL AND old_metadata IS NULL)
        OR (operation = 'INSERT' AND table_name IS NOT NULL
            AND old_metadata IS NULL AND new_metadata IS NOT NULL)
        OR (operation = 'UPDATE' AND table_name IS NOT NULL
            AND old_metadata IS NOT NULL AND new_metadata IS NOT NULL)
        OR (operation = 'DELETE' AND table_name IS NOT NULL
            AND old_metadata IS NOT NULL AND new_metadata IS NULL)
    )
);
CREATE INDEX omni_projection_event_transaction ON omni_projection_event (transaction_id);

CREATE TABLE omni_projection_job (
    event_id bigint PRIMARY KEY REFERENCES omni_projection_event,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'leased', 'retry', 'exhausted')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
    fence bigint NOT NULL DEFAULT 0 CHECK (fence >= 0),
    owner uuid,
    lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    failure_code text CHECK (failure_code ~ '^[A-Z_]{1,48}$'),
    CHECK (
        (state = 'leased' AND owner IS NOT NULL AND lease_until IS NOT NULL)
        OR (state <> 'leased' AND owner IS NULL AND lease_until IS NULL)
    ),
    CHECK (state <> 'exhausted' OR attempts = 5)
);
CREATE INDEX omni_projection_job_claim ON omni_projection_job (available_at, event_id)
    WHERE state IN ('pending', 'retry', 'leased');

CREATE FUNCTION omni_projection_enqueue() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    INSERT INTO omni_projection_job (event_id) VALUES (NEW.event_id);
    RETURN NULL;
END
$$;
CREATE TRIGGER omni_projection_enqueue AFTER INSERT ON omni_projection_event
    FOR EACH ROW EXECUTE FUNCTION omni_projection_enqueue();
ALTER TABLE omni_projection_event ENABLE ALWAYS TRIGGER omni_projection_enqueue;

CREATE FUNCTION omni_projection_metadata(value jsonb) RETURNS jsonb
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT jsonb_strip_nulls(jsonb_build_object(
        'res_id', value -> 'res_id', 'res_pid', value -> 'res_pid',
        'res_type', value -> 'res_type', 'res_ver', value -> 'res_ver',
        'pid', value -> 'pid', 'res_ver_pid', value -> 'res_ver_pid',
        'tag_id', value -> 'tag_id', 'partition_id', value -> 'partition_id',
        'res_encoding', value -> 'res_encoding',
        'golden_resource_pid', value -> 'golden_resource_pid',
        'target_pid', value -> 'target_pid', 'person_pid', value -> 'person_pid',
        'golden_resource_partition_id', value -> 'golden_resource_partition_id',
        'target_partition_id', value -> 'target_partition_id',
        'person_partition_id', value -> 'person_partition_id',
        'match_result', value -> 'match_result', 'link_source', value -> 'link_source'
    ))
$$;

CREATE FUNCTION omni_projection_capture() RETURNS trigger
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    before_value jsonb;
    after_value jsonb;
    row_value jsonb;
    candidates bigint[] := '{}';
    ids bigint[] := '{}';
    tag_ids bigint[];
    candidate bigint;
    resource_type text;
    resource_partition integer;
    unresolved boolean := false;
BEGIN
    IF TG_OP <> 'INSERT' THEN before_value := omni_projection_metadata(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN after_value := omni_projection_metadata(to_jsonb(NEW)); END IF;
    IF TG_TABLE_NAME = 'hfj_tag_def' THEN
        IF TG_OP = 'INSERT' THEN RETURN NULL; END IF;
        tag_ids := array_remove(
            ARRAY[(before_value ->> 'tag_id')::bigint, (after_value ->> 'tag_id')::bigint], NULL
        );
        SELECT coalesce(array_agg(DISTINCT res_id), '{}'),
            coalesce(bool_or(partition_id IS NOT NULL OR res_id IS NULL), false)
        INTO ids, unresolved FROM (
            SELECT res_id, partition_id FROM hfj_res_tag
                WHERE tag_id = ANY(tag_ids) AND res_type = 'Patient'
            UNION ALL
            SELECT res_id, partition_id FROM hfj_history_tag
                WHERE tag_id = ANY(tag_ids) AND res_type = 'Patient'
        ) references_to_tag;
    ELSE
        FOREACH row_value IN ARRAY ARRAY[before_value, after_value] LOOP
            IF row_value IS NULL THEN CONTINUE; END IF;
            IF TG_TABLE_NAME = 'mpi_link' THEN
                candidates := candidates || ARRAY[
                    (row_value ->> 'golden_resource_pid')::bigint,
                    (row_value ->> 'target_pid')::bigint,
                    (row_value ->> 'person_pid')::bigint
                ];
                IF row_value ->> 'partition_id' IS NOT NULL
                    OR row_value ->> 'golden_resource_partition_id' IS NOT NULL
                    OR row_value ->> 'target_partition_id' IS NOT NULL
                    OR row_value ->> 'person_partition_id' IS NOT NULL
                    OR row_value ->> 'golden_resource_pid' IS NULL
                    OR row_value ->> 'target_pid' IS NULL
                    OR row_value ->> 'person_pid' IS NULL THEN
                    unresolved := true;
                END IF;
            ELSIF TG_TABLE_NAME = 'hfj_res_ver_prov' THEN
                candidates := candidates || ARRAY[(row_value ->> 'res_pid')::bigint];
                IF row_value ->> 'res_pid' IS NULL
                    OR row_value ->> 'partition_id' IS NOT NULL THEN unresolved := true; END IF;
            ELSE
                resource_type := row_value ->> 'res_type';
                IF resource_type IS NULL THEN
                    unresolved := true;
                ELSIF resource_type = 'Patient' THEN
                    ids := ids || ARRAY[(row_value ->> 'res_id')::bigint];
                    IF row_value ->> 'partition_id' IS NOT NULL
                        OR (TG_TABLE_NAME = 'hfj_res_ver'
                            AND coalesce(row_value ->> 'res_encoding', '') NOT IN ('JSON', 'JSONC', 'DEL'))
                    THEN
                        unresolved := true;
                    END IF;
                END IF;
            END IF;
        END LOOP;
        FOREACH candidate IN ARRAY array_remove(candidates, NULL) LOOP
            SELECT res_type, partition_id INTO resource_type, resource_partition
            FROM hfj_resource WHERE res_id = candidate;
            IF NOT FOUND THEN
                ids := ids || candidate;
                unresolved := true;
            ELSIF resource_type = 'Patient' THEN
                ids := ids || candidate;
                IF resource_partition IS NOT NULL THEN unresolved := true; END IF;
            END IF;
        END LOOP;
    END IF;
    IF array_position(ids, NULL) IS NOT NULL
        OR EXISTS (SELECT FROM unnest(ids) id WHERE id <= 0) THEN
        unresolved := true;
    END IF;
    SELECT coalesce(array_agg(DISTINCT id ORDER BY id), '{}') INTO ids
        FROM unnest(ids) id WHERE id IS NOT NULL;
    IF cardinality(ids) > 0 OR unresolved THEN
        INSERT INTO omni_projection_event (
            table_name, operation, classification, affected_pids, old_metadata, new_metadata
        ) VALUES (
            TG_TABLE_NAME, TG_OP, CASE WHEN unresolved THEN 'unresolved' ELSE 'patient' END,
            ids, before_value, after_value
        );
    END IF;
    RETURN NULL;
END
$$;

CREATE FUNCTION omni_projection_deny_rewrite() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Projection capture history and input TRUNCATE are protected' USING ERRCODE = '55000';
END
$$;

DO $triggers$
DECLARE
    item record;
    name text;
BEGIN
    FOR item IN SELECT table_name FROM omni_projection_coverage ORDER BY table_name LOOP
        EXECUTE format('CREATE TRIGGER omni_projection_capture AFTER INSERT OR UPDATE OR DELETE ON %I
            FOR EACH ROW EXECUTE FUNCTION omni_projection_capture()', item.table_name);
        EXECUTE format('ALTER TABLE %I ENABLE ALWAYS TRIGGER omni_projection_capture', item.table_name);
        EXECUTE format('CREATE TRIGGER omni_projection_no_truncate BEFORE TRUNCATE ON %I
            EXECUTE FUNCTION omni_projection_deny_rewrite()', item.table_name);
        EXECUTE format('ALTER TABLE %I ENABLE ALWAYS TRIGGER omni_projection_no_truncate', item.table_name);
    END LOOP;
    FOREACH name IN ARRAY ARRAY[
        'omni_projection_event', 'omni_projection_coverage', 'omni_projection_migration'
    ] LOOP
        EXECUTE format('CREATE TRIGGER omni_projection_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON %I
            EXECUTE FUNCTION omni_projection_deny_rewrite()', name);
        EXECUTE format('ALTER TABLE %I ENABLE ALWAYS TRIGGER omni_projection_immutable', name);
    END LOOP;
END
$triggers$;
CREATE TRIGGER omni_projection_keep_jobs BEFORE DELETE OR TRUNCATE ON omni_projection_job
    EXECUTE FUNCTION omni_projection_deny_rewrite();
ALTER TABLE omni_projection_job ENABLE ALWAYS TRIGGER omni_projection_keep_jobs;

CREATE FUNCTION omni_projection_check_contract() RETURNS void
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    expected record;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed'
        OR NOT EXISTS (
            SELECT FROM omni_projection_migration
            WHERE version = 1 AND hapi_version = '8.12.0' AND stage = 'CAPTURE_ONLY'
        ) OR (SELECT count(*) FROM omni_projection_coverage) <> 7 OR EXISTS (
            SELECT FROM omni_projection_coverage k WHERE NOT EXISTS (
                SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema() AND c.relname = k.table_name
                    AND c.relkind = 'r' AND c.relpersistence = 'p'
                    AND NOT c.relrowsecurity AND NOT c.relforcerowsecurity
                    AND NOT EXISTS (
                        SELECT FROM pg_inherits WHERE inhparent = c.oid OR inhrelid = c.oid
                    )
                    AND k.columns_signature = (
                        SELECT string_agg(
                            a.attname || ':' || a.atttypid::text || ':' || a.attnotnull::text,
                            ',' ORDER BY a.attnum
                        ) FROM pg_attribute a
                        WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                    )
                    AND k.primary_key_columns = ARRAY(
                        SELECT a.attname::text FROM pg_constraint p
                        CROSS JOIN LATERAL unnest(p.conkey) WITH ORDINALITY AS key(attnum, ordinality)
                        JOIN pg_attribute a ON a.attrelid = p.conrelid AND a.attnum = key.attnum
                        WHERE p.conrelid = c.oid AND p.contype = 'p' ORDER BY key.ordinality
                    )
                    AND EXISTS (
                        SELECT FROM pg_trigger t WHERE t.tgrelid = c.oid
                            AND t.tgname = 'omni_projection_capture' AND t.tgenabled = 'A'
                            AND t.tgtype = 29 AND t.tgqual IS NULL AND t.tgnargs = 0
                            AND t.tgfoid = 'omni_projection_capture()'::regprocedure
                    )
                    AND EXISTS (
                        SELECT FROM pg_trigger t WHERE t.tgrelid = c.oid
                            AND t.tgname = 'omni_projection_no_truncate' AND t.tgenabled = 'A'
                            AND t.tgtype = 34 AND t.tgqual IS NULL AND t.tgnargs = 0
                            AND t.tgfoid = 'omni_projection_deny_rewrite()'::regprocedure
                    )
            )
        ) OR NOT EXISTS (
            SELECT FROM pg_trigger
            WHERE tgrelid = 'omni_projection_event'::regclass
                AND tgname = 'omni_projection_enqueue' AND tgenabled = 'A'
                AND tgtype = 5 AND tgqual IS NULL AND tgnargs = 0
                AND tgfoid = 'omni_projection_enqueue()'::regprocedure
        ) OR EXISTS (
            SELECT FROM omni_projection_event e
            LEFT JOIN omni_projection_job j USING (event_id) WHERE j.event_id IS NULL
        ) THEN
        RAISE EXCEPTION 'Patient projection capture contract is unavailable' USING ERRCODE = '55000';
    END IF;
    FOR expected IN SELECT * FROM (VALUES
        ('omni_projection_event', 'omni_projection_immutable', 58),
        ('omni_projection_coverage', 'omni_projection_immutable', 58),
        ('omni_projection_migration', 'omni_projection_immutable', 58),
        ('omni_projection_job', 'omni_projection_keep_jobs', 42)
    ) AS triggers(table_name, trigger_name, trigger_type) LOOP
        IF NOT EXISTS (
            SELECT FROM pg_trigger WHERE tgrelid = to_regclass(expected.table_name)
                AND tgname = expected.trigger_name AND tgenabled = 'A'
                AND tgtype = expected.trigger_type AND tgqual IS NULL AND tgnargs = 0
                AND tgfoid = 'omni_projection_deny_rewrite()'::regprocedure
        ) THEN
            RAISE EXCEPTION 'Patient projection journal protection is unavailable' USING ERRCODE = '55000';
        END IF;
    END LOOP;
END
$$;

CREATE FUNCTION omni_projection_claim(worker uuid, lease_ms integer)
RETURNS TABLE (event_id bigint, fence bigint, attempts integer)
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    IF worker IS NULL OR lease_ms IS NULL OR lease_ms < 100 OR lease_ms > 300000 THEN
        RAISE EXCEPTION 'Invalid projection worker or lease' USING ERRCODE = '22023';
    END IF;
    PERFORM omni_projection_check_contract();
    IF EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved') THEN
        RAISE EXCEPTION 'Unresolved Patient capture requires operator review' USING ERRCODE = '55000';
    END IF;
    WITH expired AS (
        SELECT j.event_id FROM omni_projection_job j
        WHERE j.state = 'leased' AND j.attempts = 5 AND j.lease_until <= clock_timestamp()
        ORDER BY j.event_id LIMIT 64 FOR UPDATE SKIP LOCKED
    )
    UPDATE omni_projection_job j SET state = 'exhausted', owner = NULL, lease_until = NULL,
        failure_code = 'LEASE_EXHAUSTED'
    FROM expired x WHERE j.event_id = x.event_id;

    RETURN QUERY
    WITH candidate AS (
        SELECT j.event_id FROM omni_projection_job j WHERE j.attempts < 5
            AND ((j.state IN ('pending', 'retry') AND j.available_at <= clock_timestamp())
                OR (j.state = 'leased' AND j.lease_until <= clock_timestamp()))
        ORDER BY j.event_id LIMIT 1 FOR UPDATE SKIP LOCKED
    )
    UPDATE omni_projection_job j SET state = 'leased', attempts = j.attempts + 1,
        fence = j.fence + 1, owner = worker,
        lease_until = clock_timestamp() + lease_ms * interval '1 millisecond', failure_code = NULL
    FROM candidate c WHERE j.event_id = c.event_id
    RETURNING j.event_id, j.fence, j.attempts;
END
$$;

CREATE FUNCTION omni_projection_fail(
    event bigint, worker uuid, token bigint, reason text, delay_ms integer
) RETURNS text LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
DECLARE
    job omni_projection_job;
BEGIN
    IF event IS NULL OR worker IS NULL OR token IS NULL OR reason IS NULL
        OR reason !~ '^[A-Z_]{1,48}$' OR delay_ms IS NULL OR delay_ms < 0 OR delay_ms > 60000 THEN
        RAISE EXCEPTION 'Invalid projection retry parameters' USING ERRCODE = '22023';
    END IF;
    PERFORM omni_projection_check_contract();
    SELECT * INTO job FROM omni_projection_job WHERE event_id = event FOR UPDATE;
    IF NOT FOUND OR job.state <> 'leased' OR job.owner IS DISTINCT FROM worker
        OR job.fence IS DISTINCT FROM token OR job.lease_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'Stale projection lease or fence' USING ERRCODE = '55000';
    END IF;
    UPDATE omni_projection_job SET
        state = CASE WHEN attempts = 5 THEN 'exhausted' ELSE 'retry' END,
        owner = NULL, lease_until = NULL, failure_code = reason,
        available_at = clock_timestamp() + delay_ms * interval '1 millisecond'
    WHERE event_id = event AND lease_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Projection lease expired before retry transition' USING ERRCODE = '55000';
    END IF;
    RETURN CASE WHEN job.attempts = 5 THEN 'EXHAUSTED' ELSE 'RETRY_SCHEDULED' END;
END
$$;

CREATE FUNCTION omni_patient_projection_read_status() RETURNS text
LANGUAGE plpgsql SET search_path FROM CURRENT AS $$
BEGIN
    PERFORM omni_projection_check_contract();
    IF EXISTS (SELECT FROM omni_projection_event WHERE classification = 'unresolved') THEN
        RETURN 'BLOCKED_UNRESOLVED_CAPTURE';
    END IF;
    IF EXISTS (SELECT FROM omni_projection_job WHERE state = 'exhausted') THEN
        RETURN 'BLOCKED_RETRY_EXHAUSTED';
    END IF;
    RETURN 'BLOCKED_CAPTURE_ONLY';
END
$$;

INSERT INTO omni_projection_migration (version, hapi_version, stage) VALUES (1, '8.12.0', 'CAPTURE_ONLY');
-- The locks are still held: the full-inventory job and later capture have no installation gap.
INSERT INTO omni_projection_event (operation, classification, affected_pids, new_metadata)
SELECT 'BOOTSTRAP', 'patient', '{}'::bigint[], jsonb_build_object(
    'patient_count', (SELECT count(*) FROM hfj_resource WHERE res_type = 'Patient'),
    'link_count', (SELECT count(*) FROM mpi_link)
);
SELECT omni_projection_check_contract();
COMMIT;
