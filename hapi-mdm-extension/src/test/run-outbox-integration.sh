#!/usr/bin/env bash
set -euo pipefail

module="$(cd -- "$(dirname -- "$0")/../.." && pwd)"
prefix="omni-outbox-it-$(date +%Y%m%d%H%M%S)-$$"
network="${prefix}-network"
database="${prefix}-db"
hapi="${prefix}-hapi"
build="${prefix}-build"
extension="${prefix}-extension"
cache="omni-hapi-mdm-test-m2"
image="hapiproject/hapi@sha256:d7f38d3676900b07e8a7d3500426eaf8d90ea9ced9a6726416f080f68e230fb0"
created_network=false
created_database=false
created_hapi=false
created_build=false
created_extension=false

cleanup() {
    local status=$?
    trap - EXIT
    if [[ "$created_hapi" == true ]]; then
        if ((status != 0)); then
            if ! docker logs --tail 1200 "$hapi" 2>&1 | grep -A 14 -E 'ERROR|Caused by:' >&2; then
                if ! docker logs --tail 60 "$hapi" >&2; then status=1; fi
            fi
        fi
        if ! docker rm -f -v "$hapi" >/dev/null; then status=1; fi
    fi
    if [[ "$created_database" == true ]]; then
        if ! docker rm -f -v "$database" >/dev/null; then status=1; fi
    fi
    if [[ "$created_network" == true ]]; then
        if ! docker network rm "$network" >/dev/null; then status=1; fi
    fi
    if [[ "$created_build" == true ]]; then
        if ! docker volume rm "$build" >/dev/null; then status=1; fi
    fi
    if [[ "$created_extension" == true ]]; then
        if ! docker volume rm "$extension" >/dev/null; then status=1; fi
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

wait_for_database() {
    docker exec "$database" sh -c '
        for i in $(seq 1 60); do
            if pg_isready -q -U outbox_test -d mdm_outbox_test; then exit 0; fi
            sleep 1
        done
        echo "Isolated PostgreSQL did not become ready" >&2
        exit 1'
}

wait_for_hapi() {
    docker exec "$database" sh -c '
        for i in $(seq 1 90); do
            if wget -q -O /dev/null http://outbox-hapi:8080/fhir/metadata 2>/dev/null; then exit 0; fi
            sleep 2
        done
        echo "Isolated HAPI did not become ready" >&2
        exit 1'
}

start_hapi() {
    local -a extra=()
    local cached_search_results_millis=0
    if [[ "$1" == guarded || "$1" == worker || "$1" == reader ]]; then
        extra=(
            -v "$extension:/app/extra-classes:ro"
            -e HAPI_FHIR_CUSTOM_BEAN_PACKAGES=ch.omnilink.fhir.mdm.extension,ch.omnilink.fhir.mdm.fixture
            -e HAPI_FHIR_CUSTOM_INTERCEPTOR_CLASSES=ch.omnilink.fhir.mdm.extension.PatientProjectionReadInterceptor
            -e OMNILINK_MDM_PROJECTION_ENABLED=true
            -e OMNILINK_MDM_PROJECTOR_TEST_FIXTURE=true
        )
    fi
    if [[ "$1" == reader ]]; then
        cached_search_results_millis=60000
    fi
    if [[ "$1" == worker ]]; then
        extra+=(-e OMNILINK_MDM_PROJECTION_WORKER_ENABLED=true)
    fi
    docker run -d --name "$hapi" --network "$network" --network-alias outbox-hapi --memory=2300m \
        -e JAVA_TOOL_OPTIONS=-Xmx1400m \
        -e SPRING_DATASOURCE_URL=jdbc:postgresql://outbox-db:5432/mdm_outbox_test \
        -e SPRING_DATASOURCE_USERNAME=outbox_test -e SPRING_DATASOURCE_PASSWORD=synthetic-only \
        -e SPRING_DATASOURCE_DRIVERCLASSNAME=org.postgresql.Driver \
        -e SPRING_JPA_PROPERTIES_HIBERNATE_DIALECT=ca.uhn.fhir.jpa.model.dialect.HapiFhirPostgresDialect \
        -e HAPI_FHIR_MDM_ENABLED=true -e HAPI_FHIR_BULK_EXPORT_ENABLED=true \
        -e "HAPI_FHIR_REUSE_CACHED_SEARCH_RESULTS_MILLIS=$cached_search_results_millis" \
        "${extra[@]}" "$image" >/dev/null
    created_hapi=true
    wait_for_hapi
}

docker volume create "$cache" >/dev/null
docker volume create "$build" >/dev/null
created_build=true
docker volume create "$extension" >/dev/null
created_extension=true
docker run --rm --network bridge -v "$module:/source:ro" -v "$build:/work" \
    -v "$extension:/extension" -v "$cache:/root/.m2" -w /work \
    maven:3.9-eclipse-temurin-17 sh -c '
        cp -R /source/. /work/ &&
        mvn clean --batch-mode --no-transfer-progress -DskipTests package &&
        cp target/hapi-mdm-projection-extension-0.1.0-SNAPSHOT.jar \
            target/hapi-mdm-projection-extension-0.1.0-SNAPSHOT-tests.jar /extension/'

docker network create --internal "$network" >/dev/null
created_network=true
docker run -d --name "$database" --network "$network" --network-alias outbox-db \
    -e POSTGRES_DB=mdm_outbox_test -e POSTGRES_USER=outbox_test -e POSTGRES_PASSWORD=synthetic-only \
    -e PGDATA=/var/lib/postgresql/outbox-data postgres:16-alpine >/dev/null
created_database=true
wait_for_database
start_hapi unguarded
docker exec "$database" wget -q -O /dev/null \
    --header="Content-Type: application/fhir+json" \
    --post-data='{"resourceType":"Patient","active":true,"identifier":[{"system":"urn:synthetic:outbox","value":"seed"}]}' \
    http://outbox-hapi:8080/fhir/Patient
docker exec "$database" wget -q -O /dev/null \
    --header="Content-Type: application/fhir+json" \
    --post-data='{"resourceType":"Practitioner","active":true}' \
    http://outbox-hapi:8080/fhir/Practitioner
docker exec "$database" sh -c '
    for i in $(seq 1 45); do
        links=$(psql -X -At -U outbox_test -d mdm_outbox_test -c "SELECT count(*) FROM mpi_link") || exit 1
        if [ "$links" -gt 0 ]; then exit 0; fi
        sleep 1
    done
    echo "Seed Patient did not receive an asynchronous MDM link" >&2
    exit 1'
docker stop "$hapi" >/dev/null
docker rm -v "$hapi" >/dev/null
created_hapi=false
docker cp "$module/src/main/resources/db/migration/V001__patient_projection_outbox.sql" \
    "$database:/tmp/outbox.sql"
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test -f /tmp/outbox.sql
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test \
    -c "SELECT * FROM omni_projection_claim('00000000-0000-4000-8000-000000000001',300000)"
fingerprint_sql="SELECT md5(jsonb_agg(to_jsonb(j) ORDER BY event_id)::text) FROM omni_projection_job j"
before="$(docker exec "$database" psql -X -At -U outbox_test -d mdm_outbox_test -c "$fingerprint_sql")"
docker restart "$database" >/dev/null
wait_for_database
after="$(docker exec "$database" psql -X -At -U outbox_test -d mdm_outbox_test -c "$fingerprint_sql")"
if [[ -z "$before" || "$before" != "$after" ]]; then
    echo "Outbox job or lease changed across PostgreSQL restart" >&2
    exit 1
fi
echo "Outbox job and lease survived orderly PostgreSQL restart"
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test \
    -c "SELECT omni_projection_fail(1,'00000000-0000-4000-8000-000000000001',1,'FIXTURE_RESTART',0)"
start_hapi guarded
docker run --rm --network "$network" -v "$build:/work" -v "$cache:/root/.m2" -w /work \
    -e MDM_OUTBOX_TEST_URL=jdbc:postgresql://outbox-db:5432/mdm_outbox_test \
    -e MDM_OUTBOX_TEST_FHIR_BASE=http://outbox-hapi:8080/fhir \
    maven:3.9-eclipse-temurin-17 \
    mvn -o --batch-mode --no-transfer-progress \
    -Dtest=GoldenIdentifierReconcilerTest,GoldenManualIdentifierPolicyTest,PatientProjectionWorkerTest,OutboxMigrationIT,OutboxHapiIT test
docker stop "$hapi" >/dev/null
docker cp "$module/src/main/resources/db/migration/V002__patient_identifier_projector.sql" \
    "$database:/tmp/projector.sql"
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test -f /tmp/projector.sql
docker start "$hapi" >/dev/null
wait_for_hapi
docker run --rm --network "$network" -v "$build:/work" -v "$cache:/root/.m2" -w /work \
    -e MDM_OUTBOX_TEST_URL=jdbc:postgresql://outbox-db:5432/mdm_outbox_test \
    -e MDM_OUTBOX_TEST_FHIR_BASE=http://outbox-hapi:8080/fhir \
    maven:3.9-eclipse-temurin-17 \
    mvn -o --batch-mode --no-transfer-progress -Dtest=PatientIdentifierProjectorIT test
docker stop "$hapi" >/dev/null
docker rm -v "$hapi" >/dev/null
created_hapi=false
docker cp "$module/src/main/resources/db/migration/V003__consistent_patient_projection_readers.sql" \
    "$database:/tmp/readers.sql"
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test -f /tmp/readers.sql
start_hapi reader
docker run --rm --network "$network" -v "$build:/work" -v "$cache:/root/.m2" -w /work \
    -e MDM_OUTBOX_TEST_URL=jdbc:postgresql://outbox-db:5432/mdm_outbox_test \
    -e MDM_OUTBOX_TEST_FHIR_BASE=http://outbox-hapi:8080/fhir \
    maven:3.9-eclipse-temurin-17 \
    mvn -o --batch-mode --no-transfer-progress -Dtest=PatientProjectionReaderV003IT test
docker stop "$hapi" >/dev/null
docker rm -v "$hapi" >/dev/null
created_hapi=false
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test -c "
    UPDATE hfj_resource SET res_ver=res_ver
    WHERE res_id=(SELECT min(res_id) FROM hfj_resource WHERE res_type='Patient');
    CREATE FUNCTION omni_test_worker_interrupt() RETURNS trigger LANGUAGE plpgsql AS
        'BEGIN PERFORM pg_sleep(60); RETURN NEW; END';
    CREATE TRIGGER omni_test_worker_interrupt BEFORE INSERT ON omni_projection_receipt
        FOR EACH ROW EXECUTE FUNCTION omni_test_worker_interrupt();"
start_hapi worker
sleeping=0
for i in $(seq 1 30); do
    sleeping="$(docker exec "$database" psql -X -At -U outbox_test -d mdm_outbox_test \
        -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event='PgSleep'")"
    if [[ "$sleeping" -gt 0 ]]; then break; fi
    sleep 1
done
if [[ "$sleeping" -eq 0 ]]; then
    echo "Automatic worker did not reach the synthetic completion barrier" >&2
    exit 1
fi
interrupted_event="$(docker exec "$database" psql -X -At -U outbox_test -d mdm_outbox_test \
    -c "SELECT event_id FROM omni_projection_job WHERE state='leased' ORDER BY event_id LIMIT 1")"
if [[ ! "$interrupted_event" =~ ^[0-9]+$ ]]; then
    echo "Automatic worker did not persist an owned claim" >&2
    exit 1
fi
docker kill --signal=KILL "$hapi" >/dev/null
for i in $(seq 1 30); do
    sleeping="$(docker exec "$database" psql -X -At -U outbox_test -d mdm_outbox_test \
        -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event='PgSleep'")"
    if [[ "$sleeping" -eq 0 ]]; then break; fi
    sleep 1
done
if [[ "$sleeping" -ne 0 ]]; then
    echo "Interrupted worker transaction did not terminate within the statement timeout" >&2
    exit 1
fi
docker exec "$database" psql -X -v ON_ERROR_STOP=1 -U outbox_test -d mdm_outbox_test -c "
    DROP TRIGGER omni_test_worker_interrupt ON omni_projection_receipt;
    DROP FUNCTION omni_test_worker_interrupt();
    DO \$verify\$ BEGIN
        IF NOT EXISTS(SELECT FROM omni_projection_job WHERE event_id=$interrupted_event
                AND state='leased' AND attempts=1 AND fence=1)
            OR EXISTS(SELECT FROM omni_projection_receipt WHERE event_id=$interrupted_event) THEN
            RAISE EXCEPTION 'Interrupted worker lost its persistent lease or falsely acknowledged';
        END IF;
    END \$verify\$;"
echo "Hard-interrupted automatic worker retained its claim without acknowledgement"
docker start "$hapi" >/dev/null
wait_for_hapi
docker run --rm --network "$network" -v "$build:/work" -v "$cache:/root/.m2" -w /work \
    -e MDM_OUTBOX_TEST_URL=jdbc:postgresql://outbox-db:5432/mdm_outbox_test \
    -e MDM_OUTBOX_TEST_FHIR_BASE=http://outbox-hapi:8080/fhir \
    -e "MDM_WORKER_RESTART_EVENT_ID=$interrupted_event" \
    maven:3.9-eclipse-temurin-17 \
    mvn -o --batch-mode --no-transfer-progress -Dtest=PatientProjectionWorkerIT test
