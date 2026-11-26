package ch.omnilink.fhir.mdm.extension;

import static ch.omnilink.fhir.mdm.extension.OutboxMigrationIT.*;
import static org.junit.jupiter.api.Assertions.*;

import ca.uhn.fhir.context.FhirContext;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.hl7.fhir.r4.model.Bundle;
import org.hl7.fhir.r4.model.Patient;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

class OutboxHapiIT {
    @Test
    void systemHistoryCannotReturnUnpublishedPatientVersions() throws Exception {
        var client = client();
        for (String route : new String[] {
            "/_history", "/_history?_count=0", "/_history?_since=9999-12-31T00:00:00Z"
        }) {
            HttpResponse<String> response = send(client, base() + route, "GET", null);
            assertEquals(503, response.statusCode(), response.body());
        }
    }

    @ParameterizedTest
    @EnumSource(value = Bundle.BundleType.class, names = {"BATCH", "TRANSACTION"})
    void embeddedPatientCountCannotBypassReadGuard(Bundle.BundleType type) throws Exception {
        Bundle request = new Bundle().setType(type);
        request.addEntry().getRequest().setMethod(Bundle.HTTPVerb.GET).setUrl("Patient?_summary=count");
        var parser = FhirContext.forR4Cached().newJsonParser();
        HttpResponse<String> response = send(client(), base(), "POST", parser.encodeResourceToString(request));
        assertEquals(200, response.statusCode(), response.body());
        Bundle result = parser.parseResource(Bundle.class, response.body());
        assertEquals(type == Bundle.BundleType.BATCH
                ? Bundle.BundleType.BATCHRESPONSE : Bundle.BundleType.TRANSACTIONRESPONSE, result.getType());
        assertEquals(1, result.getEntry().size());
        assertTrue(result.getEntryFirstRep().getResponse().getStatus().startsWith("503"), response.body());
        assertEquals("OperationOutcome", result.getEntryFirstRep().getResponse().getOutcome().fhirType());
        assertFalse(result.getEntryFirstRep().hasResource(), response.body());
    }

    @ParameterizedTest
    @EnumSource(value = Bundle.BundleType.class, names = {"BATCH", "TRANSACTION"})
    void writeOnlyBundlesRemainAvailableWhileProjectionIsBlocked(Bundle.BundleType type) throws Exception {
        Patient source = new Patient().setActive(true);
        source.addIdentifier().setSystem("urn:synthetic:outbox-bundle").setValue(UUID.randomUUID().toString());
        Bundle request = new Bundle().setType(type);
        request.addEntry().setResource(source).getRequest().setMethod(Bundle.HTTPVerb.POST).setUrl("Patient");
        var parser = FhirContext.forR4Cached().newJsonParser();
        HttpResponse<String> response = send(client(), base(), "POST", parser.encodeResourceToString(request));
        assertEquals(200, response.statusCode(), response.body());
        Bundle result = parser.parseResource(Bundle.class, response.body());
        assertEquals(type == Bundle.BundleType.BATCH
                ? Bundle.BundleType.BATCHRESPONSE : Bundle.BundleType.TRANSACTIONRESPONSE, result.getType());
        assertEquals(1, result.getEntry().size());
        assertTrue(result.getEntryFirstRep().getResponse().getStatus().startsWith("201"), response.body());
    }

    @ParameterizedTest
    @EnumSource(value = Bundle.BundleType.class, names = {"BATCH", "TRANSACTION"})
    void bundleWriteDoesNotAuthorizeItsFollowingCountRead(Bundle.BundleType type) throws Exception {
        Patient source = new Patient().setActive(true);
        source.addIdentifier().setSystem("urn:synthetic:outbox-mixed").setValue(UUID.randomUUID().toString());
        Bundle request = new Bundle().setType(type);
        request.addEntry().setResource(source).getRequest().setMethod(Bundle.HTTPVerb.POST).setUrl("Patient");
        request.addEntry().getRequest().setMethod(Bundle.HTTPVerb.GET).setUrl("Patient?_summary=count");
        var parser = FhirContext.forR4Cached().newJsonParser();
        HttpResponse<String> response = send(client(), base(), "POST", parser.encodeResourceToString(request));
        assertEquals(200, response.statusCode(), response.body());
        Bundle result = parser.parseResource(Bundle.class, response.body());
        assertEquals(2, result.getEntry().size());
        assertTrue(result.getEntry().get(0).getResponse().getStatus().startsWith("201"), response.body());
        var readEntry = result.getEntry().get(1);
        assertTrue(readEntry.getResponse().getStatus().startsWith("503"), response.body());
        assertEquals("OperationOutcome", readEntry.getResponse().getOutcome().fhirType());
        assertFalse(readEntry.hasResource(), response.body());
    }

    @Test
    void exportKickoffAndPollingCannotBypassReadGuard() throws Exception {
        var client = client();
        assertAll(java.util.stream.Stream.of(
                "/$export",
                "/Patient/$export",
                "/Group/synthetic-export-group/$export",
                "/$export-poll-status?_jobId=00000000-0000-4000-8000-000000000001"
        ).map(route -> () -> {
            HttpResponse<String> response = send(client, base() + route, "GET", null);
            assertEquals(503, response.statusCode(), route + ": " + response.body());
        }));
        HttpResponse<String> post = send(client, base() + "/$export-poll-status", "POST", """
                {"resourceType":"Parameters","parameter":[
                    {"name":"_jobId","valueString":"00000000-0000-4000-8000-000000000001"}]}
                """);
        assertEquals(503, post.statusCode(), post.body());
        HttpResponse<String> cancelled = send(client,
                base() + "/$export-poll-status?_jobId=00000000-0000-4000-8000-000000000001", "DELETE", null);
        assertEquals(404, cancelled.statusCode(), cancelled.body());
        try (Connection db = open()) {
            assertEquals("0", scalar(db,
                    "SELECT count(*) FROM bt2_job_instance WHERE definition_id='BULK_EXPORT'"),
                    "A blocked export must not enqueue background work");
        }
    }

    @ParameterizedTest
    @EnumSource(value = Bundle.BundleType.class, names = {"BATCH", "TRANSACTION"})
    void conditionalBundleCreateCannotExposeAnExistingGolden(Bundle.BundleType type) throws Exception {
        Patient source = new Patient().setActive(true);
        Bundle request = new Bundle().setType(type);
        request.addEntry().setResource(source).getRequest().setMethod(Bundle.HTTPVerb.POST)
                .setUrl("Patient").setIfNoneExist("_id=" + storedGoldenId());
        var parser = FhirContext.forR4Cached().newJsonParser();
        HttpResponse<String> response = send(client(), base(), "POST", parser.encodeResourceToString(request),
                "Prefer", "return=representation");
        if (type == Bundle.BundleType.TRANSACTION) {
            assertEquals(503, response.statusCode(), response.body());
        } else {
            assertEquals(200, response.statusCode(), response.body());
            Bundle result = parser.parseResource(Bundle.class, response.body());
            assertEquals(1, result.getEntry().size());
            assertTrue(result.getEntryFirstRep().getResponse().getStatus().startsWith("503"), response.body());
            assertFalse(result.getEntryFirstRep().hasResource(), response.body());
        }
    }

    @Test
    void realHapiWritesAndAsyncMdmCaptureContinueWhileExternalReadsAreBlocked() throws Exception {
        String base = Objects.requireNonNull(
                System.getenv("MDM_OUTBOX_TEST_FHIR_BASE"), "Set the isolated HAPI FHIR base URL");
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
        var parser = FhirContext.forR4Cached().newJsonParser();
        Patient source = new Patient();
        source.setActive(true);
        source.addIdentifier().setSystem("urn:synthetic:outbox-integration").setValue(UUID.randomUUID().toString());

        try (Connection db = open()) {
            assertEquals("CAPTURE_ONLY", scalar(db, "SELECT stage FROM omni_projection_migration"));
            long before = Long.parseLong(scalar(db, "SELECT count(*) FROM omni_projection_event"));
            HttpResponse<String> created = send(client, base + "/Patient", "POST", parser.encodeResourceToString(source));
            assertEquals(201, created.statusCode(), created.body());
            Patient stored = parser.parseResource(Patient.class, created.body());
            String id = stored.getIdElement().getIdPart();
            long pid;
            try (var statement = db.prepareStatement(
                    "SELECT res_id FROM hfj_resource WHERE res_type='Patient' AND (fhir_id=? OR res_id::text=?)")) {
                statement.setString(1, id);
                statement.setString(2, id);
                try (var rows = statement.executeQuery()) {
                    assertTrue(rows.next());
                    pid = rows.getLong(1);
                    assertFalse(rows.next());
                }
            }
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45);
            while ("0".equals(scalar(db, "SELECT count(*) FROM mpi_link WHERE target_pid=" + pid))) {
                assertTrue(System.nanoTime() < deadline, "HAPI did not complete asynchronous MDM link creation");
                Thread.sleep(250);
            }
            assertEquals("2", scalar(db, """
                    SELECT count(DISTINCT table_name) FROM omni_projection_event
                    WHERE %d=ANY(affected_pids) AND table_name IN ('hfj_resource','mpi_link')
                    """.formatted(pid)));
            assertTrue(Long.parseLong(scalar(db, "SELECT count(*) FROM omni_projection_event")) > before);

            stored.setActive(false);
            HttpResponse<String> updated = send(
                    client, base + "/Patient/" + id, "PUT", parser.encodeResourceToString(stored));
            assertEquals(200, updated.statusCode(), updated.body());
            assertEquals("true", scalar(db, """
                    SELECT EXISTS(SELECT FROM omni_projection_event
                    WHERE table_name='hfj_res_ver' AND operation='INSERT' AND %d=ANY(affected_pids))
                    """.formatted(pid)));
            assertEquals("BLOCKED_CAPTURE_ONLY", scalar(db, "SELECT omni_patient_projection_read_status()"));
            assertEquals("0", scalar(db, "SELECT count(*) FROM omni_projection_event WHERE classification='unresolved'"));
            assertEquals("0", scalar(db, """
                    SELECT count(*) FROM omni_projection_event e
                    LEFT JOIN omni_projection_job j USING(event_id) WHERE j.event_id IS NULL
                    """));

            for (String route : new String[] {
                "/Patient/" + id,
                "/Patient?_id=" + id,
                "/Patient/" + id + "/_history",
                "/Patient?_id=synthetic-nonexistent-patient",
                "/Patient?_summary=count",
                "/Patient?_count=0",
                "/$mdm-query-links?resourceType=Patient"
            }) {
                HttpResponse<String> response = send(client, base + route, "GET", null);
                assertEquals(503, response.statusCode(), route + ": " + response.body());
            }
            HttpResponse<String> existingSource = send(client, base + "/Patient", "POST",
                    parser.encodeResourceToString(source), "If-None-Exist", "_id=" + id);
            assertEquals(200, existingSource.statusCode(), existingSource.body());
            assertFalse(parser.parseResource(Patient.class, existingSource.body()).getActive());
            HttpResponse<String> existingGolden = send(client, base + "/Patient", "POST",
                    parser.encodeResourceToString(source), "If-None-Exist", "_id=" + storedGoldenId());
            assertEquals(503, existingGolden.statusCode(), existingGolden.body());
        }
    }

    private static String storedGoldenId() throws Exception {
        try (Connection db = open()) {
            return Objects.requireNonNull(scalar(db, """
                    SELECT coalesce(r.fhir_id,r.res_id::text) FROM mpi_link l
                    JOIN hfj_resource r ON r.res_id=l.golden_resource_pid
                    WHERE r.res_type='Patient' AND r.res_deleted_at IS NULL AND l.match_result=2
                    ORDER BY r.res_id LIMIT 1
                    """), "The isolated seed must have a confirmed Golden Patient");
        }
    }

    private static HttpResponse<String> send(
            HttpClient client, String url, String method, String body, String... headers)
            throws Exception {
        var request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(30))
                .header("Accept", "application/fhir+json")
                .header("Content-Type", "application/fhir+json")
                .method(method, body == null
                        ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofString(body));
        if (url.contains("/$export")) {
            request.header("Prefer", "respond-async");
        }
        if (headers.length != 0) {
            request.headers(headers);
        }
        return client.send(request.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static String base() {
        return Objects.requireNonNull(
                System.getenv("MDM_OUTBOX_TEST_FHIR_BASE"), "Set the isolated HAPI FHIR base URL");
    }

    private static HttpClient client() {
        return HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }
}
