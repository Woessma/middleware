package ch.omnilink.fhir.mdm.extension;

import static ch.omnilink.fhir.mdm.extension.OutboxMigrationIT.*;
import static org.junit.jupiter.api.Assertions.*;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.mdm.api.MdmMatchResultEnum;
import com.fasterxml.jackson.databind.ObjectMapper;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Claim;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Result;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Status;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Recovery;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Connection;
import java.sql.SQLException;
import java.time.Duration;
import java.util.Objects;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.hl7.fhir.r4.model.Patient;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class PatientIdentifierProjectorIT {
    private static final String SYSTEM = "urn:synthetic:projected";
    private final String base = Objects.requireNonNull(System.getenv("MDM_OUTBOX_TEST_FHIR_BASE"));
    private final String control = base.replaceFirst("/fhir/?$", "") + "/__omni-projector-test";
    private final HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final ObjectMapper json = new ObjectMapper();
    private record Graph(long sourcePid, long goldenPid, String sourceId, String value) {}

    @Test
    void realProjectionHasTheSameTransactionAsAckAndReplaysWithoutWriting() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        Result result = apply(claim);
        assertEquals(Status.APPLIED_NOT_PUBLISHED, result.status());
        assertTrue(result.updates() > 0);
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
        try (Connection db = open()) {
            assertEquals("acknowledged", scalar(db,
                    "SELECT state FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            assertEquals(result.transactionId(), scalar(db, """
                    SELECT transaction_id::text FROM omni_projection_event
                    WHERE table_name='hfj_resource' AND operation='UPDATE'
                        AND %d=ANY(affected_pids) ORDER BY event_id DESC LIMIT 1
                    """.formatted(graph.goldenPid())));
            assertTrue(Long.parseLong(scalar(db, """
                    SELECT count(*) FROM omni_projection_event e JOIN omni_projection_job j USING(event_id)
                    WHERE e.transaction_id='%s'::xid8 AND j.state<>'acknowledged'
                    """.formatted(result.transactionId()))) > 0, "Golden self-events must remain pending work");
        }
        String version = read(graph.goldenPid()).getIdElement().getVersionIdPart();
        assertEquals(Status.REPLAY_NOT_PUBLISHED, apply(claim).status());
        assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
        drain();
        assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
    }

    @Test
    void sourceChangesAndUnlinkRemoveOnlyPreviouslyManagedIdentifiers() throws Exception {
        Graph graph = prepare();
        Patient manual = read(graph.goldenPid());
        manual.addIdentifier().setSystem("urn:synthetic:native").setValue("native-" + graph.goldenPid());
        assertEquals(403, send(base + "/Patient/" + manual.getIdElement().getIdPart(), "PUT",
                FhirContext.forR4Cached().newJsonParser().encodeResourceToString(manual)).statusCode(),
                "The policy must not open public writes to MDM-managed Goldens");
        var nativeWrite = send(control + "/native/" + graph.goldenPid(), "POST", null);
        assertEquals(200, nativeWrite.statusCode(), nativeWrite.body());
        assertEquals(1, read(graph.goldenPid()).getIdentifier().stream()
                .filter(i -> "urn:synthetic:native".equals(i.getSystem()))
                .findFirst().orElseThrow().getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).size());
        apply(claim(30000));
        Patient changed = read(graph.sourcePid());
        changed.getIdentifier().stream().filter(i -> SYSTEM.equals(i.getSystem()))
                .findFirst().orElseThrow().setValue("replacement-" + graph.value());
        update(graph.sourceId(), changed);
        apply(claim(30000));
        Patient golden = read(graph.goldenPid());
        assertFalse(contains(golden, graph.value()));
        assertTrue(contains(golden, "replacement-" + graph.value()));
        assertTrue(golden.getIdentifier().stream().anyMatch(i -> "urn:synthetic:native".equals(i.getSystem())));
        var unlink = send(control + "/unlink", "POST",
                "{\"goldenPid\":" + graph.goldenPid() + ",\"sourcePid\":" + graph.sourcePid() + "}");
        assertEquals(200, unlink.statusCode(), unlink.body());
        assertTrue(read(graph.goldenPid()).getIdentifier().stream()
                .anyMatch(i -> "urn:synthetic:native".equals(i.getSystem())),
                "The actual HAPI NO_MATCH rebuild must preserve the explicitly manual identifier");
        apply(claim(30000));
        golden = read(graph.goldenPid());
        assertFalse(contains(golden, "replacement-" + graph.value()));
        assertFalse(golden.getIdentifier().stream().anyMatch(i -> "urn:synthetic:primary".equals(i.getSystem())));
        assertTrue(golden.getIdentifier().stream().anyMatch(i -> "urn:synthetic:native".equals(i.getSystem())));
        var nativeRemoval = send(control + "/native/" + graph.goldenPid() + "?remove=true", "POST", null);
        assertEquals(200, nativeRemoval.statusCode(), nativeRemoval.body());
        assertFalse(read(graph.goldenPid()).getIdentifier().stream()
                .anyMatch(i -> "urn:synthetic:native".equals(i.getSystem())));
    }

    @Test
    void deletedSourcesDoNotKeepManagedIdentifiersOrResurrectPatients() throws Exception {
        Graph graph = prepare();
        apply(claim(30000));
        var deleted = send(base + "/Patient/" + graph.sourceId(), "DELETE", null);
        assertEquals(200, deleted.statusCode(), deleted.body());
        try (Connection db = open()) {
            String live = scalar(db, "SELECT count(*) FROM hfj_resource WHERE res_type='Patient' AND res_deleted_at IS NULL");
            String goldenLiveSql = "SELECT EXISTS(SELECT FROM hfj_resource WHERE res_deleted_at IS NULL AND res_id=" + graph.goldenPid() + ")";
            String goldenLive = scalar(db, goldenLiveSql);
            apply(claim(30000));
            assertEquals(live, scalar(db, "SELECT count(*) FROM hfj_resource WHERE res_type='Patient' AND res_deleted_at IS NULL"));
            assertEquals("false", scalar(db, "SELECT EXISTS(SELECT FROM hfj_resource WHERE res_deleted_at IS NULL AND res_id=" + graph.sourcePid() + ")"));
            assertEquals(goldenLive, scalar(db, goldenLiveSql));
            if ("true".equals(goldenLive)) {
                assertFalse(contains(read(graph.goldenPid()), graph.value()));
            }
        }
    }

    @ParameterizedTest
    @CsvSource({"false,false", "true,false", "true,true"})
    void nativeGoldenMergeReassignsSourcesAndPreservesManualOwnership(
            boolean withManual, boolean manualPayload) throws Exception {
        Graph from = prepare();
        Graph to = prepare();
        String shared = "shared-" + UUID.randomUUID();
        for (Graph graph : new Graph[] {from, to}) {
            Patient source = read(graph.sourcePid());
            source.addIdentifier().setSystem(SYSTEM).setValue(shared);
            update(graph.sourceId(), source);
        }
        if (withManual) {
            for (Graph graph : new Graph[] {from, to}) {
                var manual = send(control + "/native/" + graph.goldenPid(), "POST", null);
                assertEquals(200, manual.statusCode(), manual.body());
            }
        }
        drain();
        var merged = send(control + "/merge?manualPayload=" + manualPayload, "POST",
                "{\"fromPid\":" + from.goldenPid() + ",\"toPid\":" + to.goldenPid() + "}");
        assertEquals(200, merged.statusCode(), merged.body());
        assertTrue(MdmResourceUtil.isGoldenRecordRedirected(read(from.goldenPid())));
        try (Connection db = open()) {
            assertEquals("2", scalar(db, "SELECT count(*) FROM mpi_link WHERE golden_resource_pid="
                    + to.goldenPid() + " AND target_pid IN (" + from.sourcePid() + "," + to.sourcePid()
                    + ") AND match_result=" + MdmMatchResultEnum.MATCH.ordinal()));
        }
        drain();
        Patient golden = read(to.goldenPid());
        assertTrue(contains(golden, from.value()));
        assertTrue(contains(golden, to.value()));
        assertEquals(List.of("Patient/" + from.sourceId(), "Patient/" + to.sourceId()).stream().sorted().toList(),
                owners(golden, shared));
        if (withManual) {
            for (Graph graph : new Graph[] {from, to}) {
                assertTrue(golden.getIdentifier().stream().anyMatch(i ->
                        "urn:synthetic:native".equals(i.getSystem())
                                && ("native-" + graph.goldenPid()).equals(i.getValue())
                                && i.getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).size() == 1));
            }
        }
        var unlinked = send(control + "/unlink", "POST",
                "{\"goldenPid\":" + to.goldenPid() + ",\"sourcePid\":" + from.sourcePid() + "}");
        assertEquals(200, unlinked.statusCode(), unlinked.body());
        drain();
        golden = read(to.goldenPid());
        assertFalse(contains(golden, from.value()));
        assertTrue(contains(golden, to.value()));
        assertEquals(List.of("Patient/" + to.sourceId()), owners(golden, shared));
        if (withManual) {
            assertEquals(2, golden.getIdentifier().stream()
                    .filter(i -> "urn:synthetic:native".equals(i.getSystem())).count());
        }
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void completionOrDeferredCommitFailureRollsBackGoldenAndAck(boolean deferred) throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        String version = read(graph.goldenPid()).getIdElement().getVersionIdPart();
        try (Connection db = open()) {
            execute(db, """
                    CREATE FUNCTION omni_test_reject_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'Synthetic completion failure'; END $$;
                    """ + (deferred ? """
                    CREATE CONSTRAINT TRIGGER omni_test_reject AFTER INSERT ON omni_projection_receipt
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION omni_test_reject_receipt()
                    """ : """
                    CREATE TRIGGER omni_test_reject BEFORE INSERT ON omni_projection_receipt
                    FOR EACH ROW EXECUTE FUNCTION omni_test_reject_receipt()
                    """));
            try {
                var response = send(control + "/apply", "POST", json.writeValueAsString(claim));
                assertEquals(500, response.statusCode(), response.body());
                assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
                assertFalse(contains(read(graph.goldenPid()), graph.value()));
                assertEquals("0", scalar(db, "SELECT count(*) FROM omni_projection_receipt WHERE event_id=" + claim.eventId()));
                assertEquals("leased", scalar(db, "SELECT state FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            } finally {
                execute(db, "DROP TRIGGER omni_test_reject ON omni_projection_receipt; DROP FUNCTION omni_test_reject_receipt()");
            }
        }
        apply(claim);
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
    }

    @Test
    void lostPostCommitResponseIsResolvedByThePersistedReceipt() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        var lost = send(control + "/apply?loseResponse=true", "POST", json.writeValueAsString(claim));
        assertEquals(503, lost.statusCode(), lost.body());
        String version = read(graph.goldenPid()).getIdElement().getVersionIdPart();
        assertEquals(Recovery.ACKNOWLEDGED_NOT_PUBLISHED, recover(claim));
        try (Connection db = open()) {
            assertNull(scalar(db, "SELECT failure_code FROM omni_projection_job WHERE event_id=" + claim.eventId()));
        }
        Result replay = apply(claim);
        assertEquals(Status.REPLAY_NOT_PUBLISHED, replay.status());
        assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
    }

    @Test
    void recoveryWaitsForAnInFlightCommitBeforeDecidingToRetry() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        try (Connection db = open()) {
            execute(db, """
                    CREATE FUNCTION omni_test_delay_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN PERFORM pg_sleep(1); RETURN NEW; END $$;
                    CREATE CONSTRAINT TRIGGER omni_test_delay AFTER INSERT ON omni_projection_receipt
                    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION omni_test_delay_receipt()
                    """);
            try {
                var applying = client.sendAsync(request(control + "/apply", "POST", json.writeValueAsString(claim)),
                        HttpResponse.BodyHandlers.ofString());
                awaitSql(db, """
                        SELECT EXISTS(SELECT FROM pg_stat_activity WHERE datname=current_database()
                            AND pid<>pg_backend_pid() AND wait_event='PgSleep')
                        """, 5000);
                assertEquals(Recovery.ACKNOWLEDGED_NOT_PUBLISHED, recover(claim));
                var applied = applying.get(10, TimeUnit.SECONDS);
                assertEquals(200, applied.statusCode(), applied.body());
                assertTrue(contains(read(graph.goldenPid()), graph.value()));
                assertEquals("acknowledged", scalar(db,
                        "SELECT state FROM omni_projection_job WHERE event_id=" + claim.eventId()));
                assertEquals("1", scalar(db,
                        "SELECT count(*) FROM omni_projection_receipt WHERE event_id=" + claim.eventId()));
            } finally {
                execute(db, "DROP TRIGGER omni_test_delay ON omni_projection_receipt; DROP FUNCTION omni_test_delay_receipt()");
            }
        }
    }

    @Test
    void lostRecoveryResponseDoesNotRepeatTheFailureTransition() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        var lost = send(control + "/recover?delay=0&loseResponse=true", "POST", json.writeValueAsString(claim));
        assertEquals(503, lost.statusCode(), lost.body());
        assertEquals(Recovery.CLAIM_LOST, recover(claim));
        assertEquals(Recovery.CLAIM_LOST, recover(new Claim(claim.eventId(), claim.owner(), claim.fence() + 1)));
        try (Connection db = open()) {
            assertEquals("retry", scalar(db, "SELECT state FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            assertEquals("1", scalar(db, "SELECT attempts FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            assertEquals("APPLY_FAILED", scalar(db,
                    "SELECT failure_code FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            assertEquals("0", scalar(db,
                    "SELECT count(*) FROM omni_projection_receipt WHERE event_id=" + claim.eventId()));
        }
        assertFalse(contains(read(graph.goldenPid()), graph.value()));
        drain();
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
    }

    @Test
    void staleFenceAndExpiredLeaseCannotWriteAGolden() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        String version = read(graph.goldenPid()).getIdElement().getVersionIdPart();
        var stale = send(control + "/apply", "POST", json.writeValueAsString(
                new Claim(claim.eventId(), claim.owner(), claim.fence() + 1)));
        assertEquals(500, stale.statusCode(), stale.body());
        assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
        apply(claim);
        Graph next = prepare();
        Claim expiring = claim(100);
        Thread.sleep(150);
        var expired = send(control + "/apply", "POST", json.writeValueAsString(expiring));
        assertEquals(500, expired.statusCode(), expired.body());
        assertFalse(contains(read(next.goldenPid()), next.value()));
        drain();
        assertTrue(contains(read(next.goldenPid()), next.value()));
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void inputWritersWaitForTheSnapshotAndTheNextRunReadsTheirCommittedChange(boolean unlink) throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        Patient changed = read(graph.sourcePid());
        changed.getIdentifier().stream().filter(i -> SYSTEM.equals(i.getSystem()))
                .findFirst().orElseThrow().setValue("concurrent-" + graph.value());
        try (Connection blocker = open(); Connection observer = open()) {
            String originalMatch = scalar(observer, "SELECT match_result FROM mpi_link WHERE golden_resource_pid="
                    + graph.goldenPid() + " AND target_pid=" + graph.sourcePid());
            blocker.setAutoCommit(false);
            execute(blocker, "SELECT * FROM omni_projection_job WHERE event_id=" + claim.eventId() + " FOR UPDATE");
            var projecting = client.sendAsync(request(control + "/apply", "POST", json.writeValueAsString(claim)),
                    HttpResponse.BodyHandlers.ofString());
            try {
                awaitSql(observer, """
                        SELECT EXISTS(SELECT FROM pg_locks WHERE relation='hfj_resource'::regclass
                            AND mode='ShareRowExclusiveLock' AND granted)
                        """, 1500);
                var writing = client.sendAsync(unlink
                                ? request(control + "/unlink", "POST",
                                    "{\"goldenPid\":" + graph.goldenPid() + ",\"sourcePid\":" + graph.sourcePid() + "}")
                                : request(base + "/Patient/" + graph.sourceId(), "PUT",
                                    FhirContext.forR4Cached().newJsonParser().encodeResourceToString(changed)),
                        HttpResponse.BodyHandlers.ofString());
                awaitSql(observer, """
                        SELECT EXISTS(SELECT FROM pg_locks WHERE relation IN (
                            SELECT to_regclass(table_name) FROM omni_projection_coverage)
                            AND mode='RowExclusiveLock' AND NOT granted)
                        """, 1200);
                assertFalse(writing.isDone());
                blocker.commit();
                var projected = projecting.get(30, TimeUnit.SECONDS);
                assertEquals(200, projected.statusCode(), projected.body());
                var written = writing.get(30, TimeUnit.SECONDS);
                assertEquals(unlink ? 500 : 200, written.statusCode(), written.body());
                if (unlink) {
                    assertEquals(originalMatch, scalar(observer, "SELECT match_result FROM mpi_link WHERE golden_resource_pid="
                            + graph.goldenPid() + " AND target_pid=" + graph.sourcePid()),
                            "Conflicting HAPI link writer must roll back, not commit a stale Golden");
                }
            } finally {
                blocker.rollback();
            }
        }
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
        assertFalse(contains(read(graph.goldenPid()), "concurrent-" + graph.value()));
        if (unlink) {
            var retried = send(control + "/unlink", "POST",
                    "{\"goldenPid\":" + graph.goldenPid() + ",\"sourcePid\":" + graph.sourcePid() + "}");
            assertEquals(200, retried.statusCode(), retried.body());
        }
        apply(claim(30000));
        assertFalse(contains(read(graph.goldenPid()), graph.value()));
        assertEquals(!unlink, contains(read(graph.goldenPid()), "concurrent-" + graph.value()));
    }

    @Test
    void sqlCompletionWithoutTheInputLockProtocolIsRejected() throws Exception {
        try (Connection db = open()) {
            SQLException failure = assertThrows(SQLException.class, () -> execute(db, """
                    SELECT omni_projection_complete(1,'00000000-0000-4000-8000-000000000001',1,0,0)
                    """));
            assertEquals("55000", failure.getSQLState());
            assertFalse("READY".equals(scalar(db, "SELECT omni_patient_projection_read_status()")));
        }
    }

    @Test
    void aBlockedProjectorTimesOutWithoutAckAndCanRetryFromFreshInputs() throws Exception {
        Graph graph = prepare();
        Claim claim = claim(30000);
        String version = read(graph.goldenPid()).getIdElement().getVersionIdPart();
        try (Connection blocker = open(); Connection observer = open()) {
            blocker.setAutoCommit(false);
            execute(blocker, "UPDATE hfj_resource SET res_ver=res_ver WHERE res_id=" + graph.sourcePid());
            long start = System.nanoTime();
            var failed = send(control + "/apply", "POST", json.writeValueAsString(claim));
            assertEquals(500, failed.statusCode(), failed.body());
            assertTrue(System.nanoTime() - start < TimeUnit.SECONDS.toNanos(10), "Lock failure must be bounded");
            assertEquals(version, read(graph.goldenPid()).getIdElement().getVersionIdPart());
            assertEquals("0", scalar(observer, "SELECT count(*) FROM omni_projection_receipt WHERE event_id=" + claim.eventId()));
            assertEquals("leased", scalar(observer, "SELECT state FROM omni_projection_job WHERE event_id=" + claim.eventId()));
            assertEquals("0", scalar(observer, """
                    SELECT count(*) FROM pg_locks WHERE mode='ShareRowExclusiveLock' AND granted
                        AND relation IN (SELECT to_regclass(table_name) FROM omni_projection_coverage)
                    """));
            blocker.rollback();
        }
        apply(claim);
        assertTrue(contains(read(graph.goldenPid()), graph.value()));
    }

    @Test
    void receiptProtectionTamperingBlocksClaimsAndExternalReads() throws Exception {
        try (Connection db = open()) {
            execute(db, "ALTER TABLE omni_projection_receipt DISABLE TRIGGER omni_projection_immutable");
            try {
                var failed = send(control + "/claim?worker=" + UUID.randomUUID(), "POST", null);
                assertEquals(500, failed.statusCode(), failed.body());
                SQLException rejected = assertThrows(SQLException.class,
                        () -> scalar(db, "SELECT omni_patient_projection_read_status()"));
                assertEquals("55000", rejected.getSQLState());
                assertEquals(500, send(base + "/Patient?_count=1", "GET", null).statusCode());
            } finally {
                execute(db, "ALTER TABLE omni_projection_receipt ENABLE ALWAYS TRIGGER omni_projection_immutable");
            }
        }
    }

    @AfterAll
    void drainingDoesNotPublishReaders() throws Exception {
        assertEquals(204, send(control + "/worker", "GET", null).statusCode(),
                "Automatic dispatch must remain opt-in during manual projector acceptance");
        drain();
        try (Connection db = open()) {
            assertEquals("0", scalar(db, "SELECT count(*) FROM omni_projection_job WHERE state<>'acknowledged'"));
            assertEquals("BLOCKED_READER_NOT_PUBLISHED", scalar(db, "SELECT omni_patient_projection_read_status()"));
        }
        assertEquals(503, send(base + "/Patient?_count=1", "GET", null).statusCode());
    }

    @ParameterizedTest
    @CsvSource({"false,false", "true,false", "true,true"})
    void nativeMergeFailureRollsBackGoldenTagsLinksAndCapture(boolean duplicate, boolean deferred) throws Exception {
        Graph from = prepare();
        Graph to = prepare();
        for (Graph graph : new Graph[] {from, to}) {
            var manual = send(control + "/native/" + graph.goldenPid(), "POST", null);
            assertEquals(200, manual.statusCode(), manual.body());
        }
        if (duplicate) {
            var linked = send(control + "/duplicate", "POST",
                    "{\"goldenPid\":" + to.goldenPid() + ",\"sourcePid\":" + from.goldenPid() + "}");
            assertEquals(200, linked.statusCode(), linked.body());
        }
        drain();
        Patient oldFrom = read(from.goldenPid());
        Patient oldTo = read(to.goldenPid());
        String command = "{\"fromPid\":" + from.goldenPid() + ",\"toPid\":" + to.goldenPid() + "}";
        try (Connection db = open()) {
            String links = linkFingerprint(db);
            String events = scalar(db, "SELECT count(*) FROM omni_projection_event");
            if (deferred) {
                execute(db, """
                        CREATE FUNCTION omni_test_reject_merge() RETURNS trigger LANGUAGE plpgsql AS $$
                        BEGIN
                            IF NEW.table_name='mpi_link' AND NEW.operation<>'DELETE' THEN
                                RAISE EXCEPTION 'Synthetic merge commit failure';
                            END IF;
                            RETURN NEW;
                        END $$;
                        CREATE CONSTRAINT TRIGGER omni_test_reject_merge
                        AFTER INSERT ON omni_projection_event DEFERRABLE INITIALLY DEFERRED
                        FOR EACH ROW EXECUTE FUNCTION omni_test_reject_merge()
                        """);
            }
            try {
                var failed = send(control + "/merge?failBeforeCommit=" + !deferred, "POST", command);
                assertEquals(500, failed.statusCode(), failed.body());
                assertTrue(oldFrom.equalsDeep(read(from.goldenPid())), "Failed merge must retain the old Golden");
                assertTrue(oldTo.equalsDeep(read(to.goldenPid())), "Failed merge must not retain target changes");
                assertEquals(links, linkFingerprint(db), "Even duplicate-link deletion must roll back");
                assertEquals(events, scalar(db, "SELECT count(*) FROM omni_projection_event"),
                        "A failed merge must leave no independently committed capture");
            } finally {
                if (deferred) {
                    execute(db, "DROP TRIGGER omni_test_reject_merge ON omni_projection_event;"
                            + "DROP FUNCTION omni_test_reject_merge()");
                }
            }
        }
        var retried = send(control + "/merge", "POST", command);
        assertEquals(200, retried.statusCode(), retried.body());
        drain();
        assertTrue(MdmResourceUtil.isGoldenRecordRedirected(read(from.goldenPid())));
        assertEquals(503, send(base + "/Patient/" + oldTo.getIdElement().getIdPart(), "GET", null).statusCode());
    }

    @Test
    void aLostMergeResponseIsNotAnInvitationToRepeatTheMerge() throws Exception {
        Graph from = prepare();
        Graph to = prepare();
        drain();
        String command = "{\"fromPid\":" + from.goldenPid() + ",\"toPid\":" + to.goldenPid() + "}";
        var lost = send(control + "/merge?loseResponse=true", "POST", command);
        assertEquals(503, lost.statusCode(), lost.body());
        Patient redirected = read(from.goldenPid());
        Patient target = read(to.goldenPid());
        assertTrue(MdmResourceUtil.isGoldenRecordRedirected(redirected));
        try (Connection db = open()) {
            String links = linkFingerprint(db);
            var repeated = send(control + "/merge", "POST", command);
            assertTrue(repeated.statusCode() >= 400, repeated.body());
            assertTrue(redirected.equalsDeep(read(from.goldenPid())));
            assertTrue(target.equalsDeep(read(to.goldenPid())));
            assertEquals(links, linkFingerprint(db));
        }
        drain();
    }

    private String linkFingerprint(Connection db) throws SQLException {
        return scalar(db, """
                SELECT md5(coalesce(jsonb_agg(to_jsonb(l) ORDER BY to_jsonb(l)::text), '[]'::jsonb)::text)
                FROM mpi_link l
                """);
    }

    private Graph prepare() throws Exception {
        Patient source = new Patient();
        source.setActive(true);
        source.addIdentifier().setSystem("urn:synthetic:primary").setValue(UUID.randomUUID().toString());
        var created = send(base + "/Patient", "POST",
                FhirContext.forR4Cached().newJsonParser().encodeResourceToString(source));
        assertEquals(201, created.statusCode(), created.body());
        String id = FhirContext.forR4Cached().newJsonParser()
                .parseResource(Patient.class, created.body()).getIdElement().getIdPart();
        long pid;
        long goldenPid;
        try (Connection db = open(); var sql = db.prepareStatement(
                "SELECT res_id FROM hfj_resource WHERE res_type='Patient' AND (fhir_id=? OR res_id::text=?)")) {
            sql.setString(1, id);
            sql.setString(2, id);
            try (var rows = sql.executeQuery()) {
                assertTrue(rows.next());
                pid = rows.getLong(1);
                assertFalse(rows.next());
            }
            awaitSql(db, "SELECT count(*)=1 FROM mpi_link WHERE target_pid=" + pid, 45000);
            goldenPid = Long.parseLong(scalar(db, "SELECT golden_resource_pid FROM mpi_link WHERE target_pid=" + pid));
        }
        String value = UUID.randomUUID().toString();
        Patient latest = read(pid);
        latest.addIdentifier().setSystem(SYSTEM).setValue(value);
        update(id, latest);
        assertFalse(contains(read(goldenPid), value), "The added identifier must be absent before projection");
        return new Graph(pid, goldenPid, id, value);
    }

    private Patient read(long pid) throws Exception {
        var response = send(control + "/patient/" + pid, "GET", null);
        assertEquals(200, response.statusCode(), response.body());
        return FhirContext.forR4Cached().newJsonParser().parseResource(Patient.class, response.body());
    }

    private Claim claim(int lease) throws Exception {
        var response = send(control + "/claim?worker=" + UUID.randomUUID() + "&lease=" + lease, "POST", null);
        assertEquals(200, response.statusCode(), response.body());
        return json.readValue(response.body(), Claim.class);
    }

    private Result apply(Claim claim) throws Exception {
        var response = send(control + "/apply", "POST", json.writeValueAsString(claim));
        assertEquals(200, response.statusCode(), response.body());
        return json.readValue(response.body(), Result.class);
    }

    private Recovery recover(Claim claim) throws Exception {
        var response = send(control + "/recover?delay=0", "POST", json.writeValueAsString(claim));
        assertEquals(200, response.statusCode(), response.body());
        return json.readValue(response.body(), Recovery.class);
    }

    private void update(String id, Patient patient) throws Exception {
        var response = send(base + "/Patient/" + id, "PUT",
                FhirContext.forR4Cached().newJsonParser().encodeResourceToString(patient));
        assertEquals(200, response.statusCode(), response.body());
    }

    private void drain() throws Exception {
        for (int attempt = 0; attempt < 300; attempt++) {
            var response = send(control + "/claim?worker=" + UUID.randomUUID(), "POST", null);
            if (response.statusCode() == 204) {
                return;
            }
            assertEquals(200, response.statusCode(), response.body());
            apply(json.readValue(response.body(), Claim.class));
        }
        fail("Projection did not converge within 300 jobs");
    }

    private List<String> owners(Patient patient, String value) {
        return patient.getIdentifier().stream()
                .filter(i -> SYSTEM.equals(i.getSystem()) && value.equals(i.getValue()))
                .findFirst().orElseThrow().getExtensionsByUrl(GoldenIdentifierReconciler.SOURCE).stream()
                .map(e -> ((org.hl7.fhir.r4.model.Reference) e.getValue()).getReference()).sorted().toList();
    }

    private boolean contains(Patient patient, String value) {
        return patient.getIdentifier().stream().anyMatch(i -> SYSTEM.equals(i.getSystem()) && value.equals(i.getValue()));
    }

    private static void awaitSql(Connection db, String sql, long timeoutMillis) throws Exception {
        long end = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        while (!"true".equals(scalar(db, sql))) {
            assertTrue(System.nanoTime() < end, "Timed out waiting for the PostgreSQL test condition");
            Thread.sleep(25);
        }
    }

    private HttpResponse<String> send(String url, String method, String body) throws Exception {
        return client.send(request(url, method, body), HttpResponse.BodyHandlers.ofString());
    }

    private HttpRequest request(String url, String method, String body) {
        return HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(45))
                .header("Content-Type", "application/json")
                .header("Accept", url.startsWith(control + "/patient/") ? "application/fhir+json" : "application/json")
                .method(method, body == null
                        ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body)).build();
    }
}
