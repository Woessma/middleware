package ch.omnilink.fhir.mdm.extension;

import static ch.omnilink.fhir.mdm.extension.OutboxMigrationIT.*;
import static org.junit.jupiter.api.Assertions.*;

import ca.uhn.fhir.context.FhirContext;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.URLDecoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.hl7.fhir.r4.model.Binary;
import org.hl7.fhir.r4.model.Bundle;
import org.hl7.fhir.r4.model.Patient;
import org.junit.jupiter.api.Test;

class PatientProjectionReaderV003IT {
    private static final FhirContext FHIR = FhirContext.forR4Cached();

    @Test
    void readyPatientReadsCountHistoryAndFollowupPagesRemainAvailable() throws Exception {
        try (Connection db = open()) {
            assertEquals("READY", scalar(db, "SELECT omni_patient_projection_read_status()"));
        }
        String patientId;
        try (Connection db = open()) {
            patientId = Objects.requireNonNull(scalar(db, """
                    SELECT coalesce(fhir_id,res_id::text) FROM hfj_resource
                    WHERE res_type='Patient' AND res_deleted_at IS NULL
                    ORDER BY res_id LIMIT 1
                    """));
        }
        assertEquals(200, get(base() + "/Patient/" + patientId).statusCode());
        assertEquals(200, get(base() + "/Patient/" + patientId + "/_history").statusCode());

        var empty = get(base() + "/Patient?identifier=urn%3Asynthetic%3Amissing%7C" + UUID.randomUUID()
                + "&_summary=count");
        assertEquals(200, empty.statusCode(), empty.body());
        Bundle emptyBundle = FHIR.newJsonParser().parseResource(Bundle.class, empty.body());
        assertEquals(0, emptyBundle.getTotal());
        assertEquals(200, get(base() + "/Patient?_count=0").statusCode());

        var firstPage = get(base() + "/Patient?_count=1&_sort=_id");
        assertEquals(200, firstPage.statusCode(), firstPage.body());
        Bundle firstBundle = FHIR.newJsonParser().parseResource(Bundle.class, firstPage.body());
        String next = firstBundle.getLink().stream()
                .filter(link -> "next".equals(link.getRelation()))
                .map(Bundle.BundleLinkComponent::getUrl)
                .findFirst()
                .orElseThrow(() -> new AssertionError("Expected a second Patient search page"));
        var secondPage = get(next);
        assertEquals(200, secondPage.statusCode(), secondPage.body());
        Bundle secondBundle = FHIR.newJsonParser().parseResource(Bundle.class, secondPage.body());
        assertFalse(secondBundle.getEntry().isEmpty());
        assertNotEquals(firstBundle.getEntryFirstRep().getResource().getIdElement().getIdPart(),
                secondBundle.getEntryFirstRep().getResource().getIdElement().getIdPart());
    }

    @Test
    void patientHttpRequestHoldsReaderLockAgainstWriters() throws Exception {
        String patientId;
        try (Connection db = open()) {
            patientId = Objects.requireNonNull(scalar(db, """
                    SELECT coalesce(fhir_id,res_id::text) FROM hfj_resource
                    WHERE res_type='Patient' AND res_deleted_at IS NULL
                    ORDER BY res_id LIMIT 1
                    """));
        }

        var request = HttpRequest.newBuilder(URI.create(base() + "/Patient/" + patientId))
                .timeout(Duration.ofSeconds(15))
                .header("Accept", "application/fhir+json")
                .header("X-Omni-Test-Hold-Reader-Lock", "true")
                .GET()
                .build();
        var response = client().sendAsync(request, HttpResponse.BodyHandlers.ofString());

        long deadline = System.nanoTime() + Duration.ofSeconds(10).toNanos();
        int readerPid = -1;
        try (Connection db = open();
                var activeReader = db.prepareStatement("""
                        SELECT pid FROM pg_stat_activity
                        WHERE application_name = 'omni-projection-reader-lock'
                        """)) {
            while (System.nanoTime() < deadline) {
                try (var rows = activeReader.executeQuery()) {
                    if (rows.next()) {
                        readerPid = rows.getInt(1);
                        break;
                    }
                }
                Thread.sleep(25);
            }
            assertTrue(readerPid > 0, "FHIR request did not reach the in-transaction reader-lock probe");
            String observedLocks;
            try (var observed = db.prepareStatement("""
                    SELECT coalesce(string_agg(
                        format('%s/%s/%s/%s/%s/%s', classid, objid, objsubid, mode, granted, fastpath), ','),
                        'none') FROM pg_locks WHERE locktype = 'advisory' AND pid = ?
                    """)) {
                observed.setInt(1, readerPid);
                try (var rows = observed.executeQuery()) {
                    assertTrue(rows.next());
                    observedLocks = rows.getString(1);
                }
            }
            try (var lock = db.prepareStatement("""
                    SELECT EXISTS (
                        SELECT FROM pg_locks
                        WHERE locktype = 'advisory' AND pid = ?
                            AND classid = 1330462281 AND objid = 1296323889
                            AND objsubid = 2 AND mode = 'ShareLock' AND granted
                    )
                    """)) {
                lock.setInt(1, readerPid);
                try (var rows = lock.executeQuery()) {
                    assertTrue(rows.next() && rows.getBoolean(1),
                        "FHIR request does not hold the V003 reader lock; observed="
                                    + observedLocks);
                }
            }
        }

        try (Connection writer = open()) {
            writer.setAutoCommit(false);
            try (var statement = writer.createStatement()) {
                statement.execute("SET LOCAL lock_timeout = '500ms'");
                SQLException blocked = assertThrows(SQLException.class, () -> {
                    try (var rows = statement.executeQuery(
                            "SELECT pg_advisory_xact_lock(1330462281, 1296323889)")) {
                        assertTrue(rows.next());
                    }
                });
                assertEquals("55P03", blocked.getSQLState(),
                        "A concurrent projection writer must wait for the Patient read request");
            } finally {
                writer.rollback();
            }
        }

        var completed = response.get(10, TimeUnit.SECONDS);
        assertEquals(200, completed.statusCode(), completed.body());
    }

    @Test
    void legacyExportJobsAndBinaryUrlsAreRejected() throws Exception {
        String jobId = "legacy-" + UUID.randomUUID();
        Binary binary = new Binary().setContentType("text/plain").setData("synthetic".getBytes());
        var created = post(base() + "/Binary", FHIR.newJsonParser().encodeResourceToString(binary));
        assertEquals(201, created.statusCode(), created.body());
        String binaryId = FHIR.newJsonParser().parseResource(Binary.class, created.body())
                .getIdElement().getIdPart();

        try (Connection db = open()) {
            try (var statement = db.prepareStatement(
                    "INSERT INTO omni_projection_legacy_export_job(job_id) VALUES (?)")) {
                statement.setString(1, jobId);
                statement.executeUpdate();
            }
            try (var statement = db.prepareStatement(
                    "INSERT INTO omni_projection_legacy_export_binary(binary_id, job_id) VALUES (?, ?)")) {
                statement.setString(1, binaryId);
                statement.setString(2, jobId);
                statement.executeUpdate();
            }
        }

        var poll = get(base() + "/$export-poll-status?_jobId=" + jobId);
        assertEquals(410, poll.statusCode(), poll.body());
        var download = get(base() + "/Binary/" + binaryId);
        assertEquals(410, download.statusCode(), download.body());
    }

    @Test
    void currentBulkExportPollsAndItsBinaryContentCanBeDownloaded() throws Exception {
        var kickoff = client().send(HttpRequest.newBuilder(URI.create(base() + "/Patient/$export?_type=Patient"))
                        .timeout(Duration.ofSeconds(30))
                        .header("Accept", "application/fhir+json")
                        .header("Prefer", "respond-async")
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(202, kickoff.statusCode(), kickoff.body());
        String location = kickoff.headers().firstValue("Content-Location")
                .or(() -> kickoff.headers().firstValue("Location"))
                .orElseThrow(() -> new AssertionError("Bulk export response omitted its polling URL"));
        String pollUrl = URI.create(base() + "/").resolve(location).toString();

        HttpResponse<String> completed = null;
        long deadline = System.nanoTime() + Duration.ofMinutes(3).toNanos();
        while (System.nanoTime() < deadline) {
            var response = get(pollUrl);
            if (response.statusCode() == 200) {
                completed = response;
                break;
            }
            assertEquals(202, response.statusCode(), response.body());
            Thread.sleep(500);
        }
        assertNotNull(completed, "Bulk export did not complete before the deadline");
        assertFalse(completed.body().isBlank(),
                "Bulk export poll returned an empty body; headers=" + completed.headers().map());
        JsonNode report = new ObjectMapper().readTree(completed.body());
        assertTrue(report.hasNonNull("transactionTime"), completed.body());
        assertTrue(report.path("error").isArray(), completed.body());
        assertEquals(0, report.path("error").size(), completed.body());
        JsonNode outputs = report.path("output");
        assertTrue(outputs.isArray() && !outputs.isEmpty(), completed.body());
        assertEquals("Patient", outputs.get(0).path("type").asText(), completed.body());
        String binaryUrl = outputs.get(0).path("url").asText();
        assertFalse(binaryUrl.isBlank(), completed.body());
        String jobId = queryValue(pollUrl, "_jobId");
        JsonNode storedReport = new ObjectMapper().readTree(batch2Report(jobId));
        JsonNode binaryMap = storedReport.path("resourceType2BinaryIds");
        assertTrue(binaryMap.isObject(), storedReport.toString());
        String binaryPath = URI.create(binaryUrl).getPath();
        int binaryPathStart = binaryPath.lastIndexOf("/Binary/");
        assertTrue(binaryPathStart >= 0, binaryUrl);
        String binaryId = binaryPath.substring(binaryPathStart + "/Binary/".length()).split("/", 2)[0];
        assertTrue(containsBinaryId(binaryMap, binaryId), binaryUrl + " was not listed in " + storedReport);
        var download = get(URI.create(base() + "/").resolve(binaryUrl).toString());
        assertEquals(200, download.statusCode(), download.body());
        assertFalse(download.body().isBlank(), "Bulk export Binary content must not be empty");
    }

    private static String batch2Report(String jobId) throws Exception {
        try (Connection db = open();
                var statement = db.prepareStatement("""
                        SELECT coalesce(nullif(report_vc, ''),
                            CASE WHEN report IS NOT NULL THEN convert_from(lo_get(report), 'UTF8') END)
                        FROM bt2_job_instance WHERE id = ?
                        """)) {
            statement.setString(1, jobId);
            try (var rows = statement.executeQuery()) {
                assertTrue(rows.next(), "Batch2 export job was not persisted");
                return Objects.requireNonNull(rows.getString(1), "Batch2 export report is missing");
            }
        }
    }

    private static boolean containsBinaryId(JsonNode binaryMap, String binaryId) {
        var resources = binaryMap.elements();
        while (resources.hasNext()) {
            var binaries = resources.next();
            if (binaries.isArray()) {
                for (JsonNode candidate : binaries) {
                    String reference = candidate.asText();
                    if (reference.startsWith("Binary/" + binaryId)
                            && (reference.length() == "Binary/".length() + binaryId.length()
                                    || reference.charAt("Binary/".length() + binaryId.length()) == '/')) {
                        return true;
                    }
                }
            }
        }
        return false;
    }

    private static String queryValue(String url, String name) {
        String query = Objects.requireNonNull(URI.create(url).getRawQuery(), "Expected polling query parameters");
        for (String parameter : query.split("&")) {
            int separator = parameter.indexOf('=');
            if (separator > 0 && name.equals(URLDecoder.decode(parameter.substring(0, separator), StandardCharsets.UTF_8))) {
                return URLDecoder.decode(parameter.substring(separator + 1), StandardCharsets.UTF_8);
            }
        }
        throw new AssertionError("Polling URL omitted " + name);
    }

    private static HttpResponse<String> get(String url) throws Exception {
        return client().send(HttpRequest.newBuilder(URI.create(url))
                        .timeout(Duration.ofSeconds(30))
                        .header("Accept", "application/fhir+json")
                        .GET()
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private static HttpResponse<String> post(String url, String body) throws Exception {
        return client().send(HttpRequest.newBuilder(URI.create(url))
                        .timeout(Duration.ofSeconds(30))
                        .header("Accept", "application/fhir+json")
                        .header("Content-Type", "application/fhir+json")
                        .POST(HttpRequest.BodyPublishers.ofString(body))
                        .build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private static HttpClient client() {
        return HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    }

    private static String base() {
        return Objects.requireNonNull(
                System.getenv("MDM_OUTBOX_TEST_FHIR_BASE"), "Set the isolated HAPI FHIR base URL");
    }
}
