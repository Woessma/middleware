package ch.omnilink.fhir.mdm.extension;

import static ch.omnilink.fhir.mdm.extension.OutboxMigrationIT.*;
import static org.junit.jupiter.api.Assertions.*;

import ca.uhn.fhir.context.FhirContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.hl7.fhir.r4.model.Patient;
import org.junit.jupiter.api.Test;

class PatientProjectionWorkerIT {
    private static final String SYSTEM = "urn:synthetic:worker";
    private final String base = Objects.requireNonNull(System.getenv("MDM_OUTBOX_TEST_FHIR_BASE"));
    private final String control = base.replaceFirst("/fhir/?$", "") + "/__omni-projector-test";
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void schedulerRecoversADeadWorkerProjectsChangesAndStopsAtTheRetryBudget() throws Exception {
        long interrupted = Long.parseLong(Objects.requireNonNull(System.getenv("MDM_WORKER_RESTART_EVENT_ID")));
        assertEquals(200, send(control + "/worker", "GET", null).statusCode());
        try (Connection db = open()) {
            awaitSql(db, "SELECT state='acknowledged' FROM omni_projection_job WHERE event_id=" + interrupted, 60000);
            assertEquals("2", scalar(db, "SELECT fence FROM omni_projection_job WHERE event_id=" + interrupted));
            assertEquals("2", scalar(db, "SELECT attempts FROM omni_projection_job WHERE event_id=" + interrupted));
            assertEquals("1", scalar(db, "SELECT count(*) FROM omni_projection_receipt WHERE event_id=" + interrupted));

            Patient source = new Patient();
            source.setActive(true);
            source.addIdentifier().setSystem("urn:synthetic:worker-primary").setValue(UUID.randomUUID().toString());
            var created = send(base + "/Patient", "POST", encode(source));
            assertEquals(201, created.statusCode(), created.body());
            String id = FhirContext.forR4Cached().newJsonParser()
                    .parseResource(Patient.class, created.body()).getIdElement().getIdPart();
            long sourcePid;
            try (var sql = db.prepareStatement(
                    "SELECT res_id FROM hfj_resource WHERE res_type='Patient' AND coalesce(fhir_id,res_id::text)=?")) {
                sql.setString(1, id);
                try (var rows = sql.executeQuery()) {
                    assertTrue(rows.next());
                    sourcePid = rows.getLong(1);
                    assertFalse(rows.next());
                }
            }
            awaitSql(db, "SELECT count(*)=1 FROM mpi_link WHERE target_pid=" + sourcePid, 45000);
            long goldenPid = Long.parseLong(scalar(db,
                    "SELECT golden_resource_pid FROM mpi_link WHERE target_pid=" + sourcePid));
            String value = UUID.randomUUID().toString();
            source = read(sourcePid);
            source.addIdentifier().setSystem(SYSTEM).setValue(value);
            var written = send(base + "/Patient/" + id, "PUT", encode(source));
            assertEquals(200, written.statusCode(), written.body());
            awaitGolden(goldenPid, value);
            awaitSql(db, "SELECT count(*)=0 FROM omni_projection_job WHERE state<>'acknowledged'", 90000);
            assertEquals("BLOCKED_READER_NOT_PUBLISHED", scalar(db, "SELECT omni_patient_projection_read_status()"));
            var state = send(control + "/worker", "GET", null);
            assertEquals(200, state.statusCode(), state.body());
            assertTrue(json.readTree(state.body()).hasNonNull("lastCompletionObservedAt"));
            String version = read(goldenPid).getIdElement().getVersionIdPart();
            Thread.sleep(2200);
            assertEquals(version, read(goldenPid).getIdElement().getVersionIdPart(), "Idle polling must not rewrite Goldens");

            execute(db, """
                    CREATE FUNCTION omni_test_worker_failure() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'Synthetic worker completion failure'; END $$;
                    CREATE TRIGGER omni_test_worker_failure BEFORE INSERT ON omni_projection_receipt
                    FOR EACH ROW EXECUTE FUNCTION omni_test_worker_failure()
                    """);
            try {
                source = read(sourcePid);
                source.getIdentifier().stream().filter(i -> SYSTEM.equals(i.getSystem()))
                        .findFirst().orElseThrow().setValue("failed-" + value);
                written = send(base + "/Patient/" + id, "PUT", encode(source));
                assertEquals(200, written.statusCode(), written.body());
                awaitSql(db, "SELECT EXISTS(SELECT FROM omni_projection_job WHERE state='exhausted')", 60000);
                assertEquals("BLOCKED_RETRY_EXHAUSTED", scalar(db, "SELECT omni_patient_projection_read_status()"));
                assertEquals("5", scalar(db, "SELECT min(attempts) FROM omni_projection_job WHERE state='exhausted'"));
                assertEquals("APPLY_FAILED", scalar(db,
                        "SELECT failure_code FROM omni_projection_job WHERE state='exhausted' ORDER BY event_id LIMIT 1"));
                assertEquals("0", scalar(db, """
                        SELECT count(*) FROM omni_projection_receipt r JOIN omni_projection_job j USING(event_id)
                        WHERE j.state='exhausted'
                        """));
                assertTrue(contains(read(goldenPid), value));
                assertFalse(contains(read(goldenPid), "failed-" + value));
                long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(5);
                while (true) {
                    state = send(control + "/worker", "GET", null);
                    assertEquals(200, state.statusCode(), state.body());
                    if ("BLOCKED_RETRY_EXHAUSTED".equals(json.readTree(state.body()).path("phase").asText())) {
                        break;
                    }
                    assertTrue(System.nanoTime() < end, "Worker did not expose exhausted status");
                    Thread.sleep(50);
                }
                String attempts = scalar(db, "SELECT sum(attempts) FROM omni_projection_job");
                Thread.sleep(2200);
                assertEquals(attempts, scalar(db, "SELECT sum(attempts) FROM omni_projection_job"),
                        "An exhausted global projection must stop consuming other job budgets");
                assertEquals(503, send(base + "/Patient?_count=1", "GET", null).statusCode());
            } finally {
                execute(db, "DROP TRIGGER omni_test_worker_failure ON omni_projection_receipt; DROP FUNCTION omni_test_worker_failure()");
            }
        }
    }

    private void awaitGolden(long pid, String value) throws Exception {
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
        while (!contains(read(pid), value)) {
            assertTrue(System.nanoTime() < end, "Scheduler did not project the actual source identifier");
            Thread.sleep(100);
        }
    }

    private static void awaitSql(Connection db, String sql, long timeoutMillis) throws Exception {
        long end = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        while (!"true".equals(scalar(db, sql))) {
            assertTrue(System.nanoTime() < end, "Timed out waiting for the worker database condition");
            Thread.sleep(100);
        }
    }

    private Patient read(long pid) throws Exception {
        var response = send(control + "/patient/" + pid, "GET", null);
        assertEquals(200, response.statusCode(), response.body());
        return FhirContext.forR4Cached().newJsonParser().parseResource(Patient.class, response.body());
    }

    private static String encode(Patient patient) {
        return FhirContext.forR4Cached().newJsonParser().encodeResourceToString(patient);
    }

    private static boolean contains(Patient patient, String value) {
        return patient.getIdentifier().stream().anyMatch(i -> SYSTEM.equals(i.getSystem()) && value.equals(i.getValue()));
    }

    private HttpResponse<String> send(String url, String method, String body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(45))
                .header("Content-Type", "application/json")
                .header("Accept", url.startsWith(control + "/patient/") ? "application/fhir+json" : "application/json")
                .method(method, body == null
                        ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body)).build();
        return client.send(request, HttpResponse.BodyHandlers.ofString());
    }
}
