package ch.omnilink.fhir.mdm.extension;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class OutboxMigrationIT {
    private static final String[] INPUTS = {
        "hfj_resource", "hfj_res_ver", "hfj_res_tag", "hfj_history_tag",
        "hfj_tag_def", "hfj_res_ver_prov", "mpi_link"
    };
    private Connection connection;
    private String schema;
    private long patient;
    private long practitioner;

    static Connection open() throws SQLException {
        String url = Objects.requireNonNull(
                System.getenv("MDM_OUTBOX_TEST_URL"), "Set MDM_OUTBOX_TEST_URL to the isolated test database");
        Connection result = DriverManager.getConnection(url, "outbox_test", "synthetic-only");
        try {
            assertEquals("mdm_outbox_test", scalar(result, "SELECT current_database()"),
                    "These tests must never run against the lab or production HAPI database");
            execute(result, "SET statement_timeout='15s'; SET lock_timeout='2s'");
            return result;
        } catch (SQLException | RuntimeException | AssertionError failure) {
            result.close();
            throw failure;
        }
    }

    static String migration() throws Exception {
        try (var source = OutboxMigrationIT.class.getResourceAsStream(
                "/db/migration/V001__patient_projection_outbox.sql")) {
            return new String(Objects.requireNonNull(source).readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    static void execute(Connection db, String sql) throws SQLException {
        try (var statement = db.createStatement()) {
            statement.execute(sql);
        }
    }

    static String scalar(Connection db, String sql) throws SQLException {
        try (var statement = db.createStatement(); var rows = statement.executeQuery(sql)) {
            assertTrue(rows.next(), "Expected a query result");
            Object value = rows.getObject(1);
            return value == null ? null : value.toString();
        }
    }

    private String value(String sql) throws SQLException {
        return scalar(connection, sql);
    }

    private long count() throws SQLException {
        return Long.parseLong(value("SELECT count(*) FROM omni_projection_event"));
    }

    private void install() throws Exception {
        execute(connection, migration());
    }

    private Connection another() throws SQLException {
        Connection db = open();
        execute(db, "SET search_path=" + schema + ",pg_catalog");
        return db;
    }

    @BeforeEach
    void setUp() throws Exception {
        connection = open();
        schema = "omni_outbox_test_" + UUID.randomUUID().toString().replace("-", "");
        execute(connection, "CREATE SCHEMA " + schema + "; SET search_path=" + schema + ",pg_catalog");
        for (String table : INPUTS) {
            execute(connection, "CREATE TABLE " + table + " (LIKE public." + table + " INCLUDING ALL)");
            execute(connection, "INSERT INTO " + table + " SELECT * FROM public." + table);
        }
        patient = Long.parseLong(value(
                "SELECT res_id FROM hfj_resource WHERE res_type='Patient' ORDER BY res_id LIMIT 1"));
        practitioner = Long.parseLong(value(
                "SELECT res_id FROM hfj_resource WHERE res_type='Practitioner' ORDER BY res_id LIMIT 1"));
    }

    @AfterEach
    void tearDown() throws Exception {
        if (connection != null) {
            connection.close();
        }
        if (schema != null) {
            try (Connection db = open()) {
                execute(db, "DROP SCHEMA " + schema + " CASCADE");
            }
        }
    }

    @Test
    void existingPatientsProduceAFullInventoryJobWithoutPublication() throws Exception {
        String patients = value("SELECT count(*) FROM hfj_resource WHERE res_type='Patient'");
        install();
        assertEquals(patients, value(
                "SELECT new_metadata->>'patient_count' FROM omni_projection_event WHERE operation='BOOTSTRAP'"));
        assertEquals("1", value("SELECT count(*) FROM omni_projection_job"));
        assertEquals("BLOCKED_CAPTURE_ONLY", value("SELECT omni_patient_projection_read_status()"));
        SQLException error = assertThrows(SQLException.class,
                () -> execute(connection, "UPDATE omni_projection_job SET state='acknowledged'"));
        assertEquals("23514", error.getSQLState());
    }

    @Test
    void patientWritesAndTheirJobsCommitOrRollBackTogether() throws Exception {
        install();
        long baseline = count();
        connection.setAutoCommit(false);
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
        assertEquals(baseline + 1, count());
        assertEquals("true", value("""
                SELECT bool_and(e.transaction_id=pg_current_xact_id()) FROM omni_projection_event e
                WHERE operation='UPDATE'
                """));
        try (Connection other = another()) {
            assertEquals(Long.toString(baseline), scalar(other, "SELECT count(*) FROM omni_projection_event"));
        }
        connection.rollback();
        assertEquals(baseline, count());
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
        connection.commit();
        assertEquals(baseline + 1, count());
        assertEquals(Long.toString(baseline + 1), value("SELECT count(*) FROM omni_projection_job"));
    }

    @Test
    void providerOnlyChangesDoNotEnqueuePatientWork() throws Exception {
        install();
        long before = count();
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + practitioner);
        assertEquals(before, count());
    }

    @Test
    void historyRewriteAndProvenanceAreCapturedWithoutPayloads() throws Exception {
        install();
        execute(connection, "UPDATE hfj_res_ver SET res_text_vc='synthetic-private-payload' WHERE res_id=" + patient);
        execute(connection, """
                INSERT INTO hfj_res_ver_prov (res_ver_pid,res_pid,source_uri)
                SELECT pid,res_id,'synthetic-private-provenance' FROM hfj_res_ver
                WHERE res_id=%d LIMIT 1
                """.formatted(patient));
        assertEquals("2", value("""
                SELECT count(DISTINCT table_name) FROM omni_projection_event
                WHERE table_name IN ('hfj_res_ver','hfj_res_ver_prov')
                """));
        assertEquals("false", value("""
                SELECT EXISTS(SELECT FROM omni_projection_event
                WHERE old_metadata::text LIKE '%synthetic-private%'
                    OR new_metadata::text LIKE '%synthetic-private%')
                """));
    }

    @Test
    void resourceAndHistoryTagsAndSharedDefinitionChangesInvalidatePatients() throws Exception {
        install();
        execute(connection, "INSERT INTO hfj_tag_def(tag_id,tag_type,tag_code) VALUES(900001,0,'synthetic')");
        execute(connection, """
                INSERT INTO hfj_res_tag(pid,tag_id,res_id,res_type) VALUES(900001,900001,%d,'Patient');
                INSERT INTO hfj_history_tag(pid,tag_id,res_id,res_type,res_ver_pid)
                SELECT 900001,900001,res_id,'Patient',pid FROM hfj_res_ver WHERE res_id=%d LIMIT 1;
                UPDATE hfj_tag_def SET tag_code='changed' WHERE tag_id=900001
                """.formatted(patient, patient));
        assertEquals("3", value("""
                SELECT count(DISTINCT table_name) FROM omni_projection_event
                WHERE table_name IN ('hfj_res_tag','hfj_history_tag','hfj_tag_def')
                """));
        assertEquals("true", value("""
                SELECT bool_and(affected_pids=ARRAY[%d]::bigint[]) FROM omni_projection_event
                WHERE table_name IN ('hfj_res_tag','hfj_history_tag','hfj_tag_def')
                """.formatted(patient)));
    }

    @Test
    void linkMoveAndDeleteRetainOldAndNewPatientEndpoints() throws Exception {
        install();
        execute(connection, """
                INSERT INTO mpi_link(pid,created,updated,golden_resource_pid,target_pid,person_pid,
                    link_source,match_result,version)
                VALUES(900001,now(),now(),%d,%d,%d,0,0,'synthetic')
                """.formatted(patient, patient, patient));
        execute(connection, "UPDATE mpi_link SET golden_resource_pid=" + practitioner + " WHERE pid=900001");
        execute(connection, "DELETE FROM mpi_link WHERE pid=900001");
        assertEquals("3", value("SELECT count(*) FROM omni_projection_event WHERE table_name='mpi_link'"));
        assertEquals("true", value("""
                SELECT bool_and(%d=ANY(affected_pids)) FROM omni_projection_event WHERE table_name='mpi_link'
                """.formatted(patient)));
        assertEquals(Long.toString(patient), value("""
                SELECT (old_metadata->>'golden_resource_pid') FROM omni_projection_event
                WHERE table_name='mpi_link' AND operation='UPDATE'
                """));
        assertEquals(Long.toString(practitioner), value("""
                SELECT (new_metadata->>'golden_resource_pid') FROM omni_projection_event
                WHERE table_name='mpi_link' AND operation='UPDATE'
                """));
    }

    @Test
    void missingEndpointsAndUnsupportedPartitionsBlockInsteadOfLosingWork() throws Exception {
        install();
        execute(connection, """
                INSERT INTO hfj_res_ver_prov(res_ver_pid,res_pid) VALUES(900001,999999);
                """);
        assertEquals("BLOCKED_UNRESOLVED_CAPTURE", value("SELECT omni_patient_projection_read_status()"));
        assertThrows(SQLException.class,
                () -> value("SELECT * FROM omni_projection_claim('" + UUID.randomUUID() + "',1000)"));
        execute(connection, "UPDATE hfj_resource SET partition_id=42 WHERE res_id=" + patient);
        assertEquals("2", value("SELECT count(*) FROM omni_projection_event WHERE classification='unresolved'"));
    }

    @Test
    void claimsSkipLockedJobsAndStaleFencesCannotScheduleRetries() throws Exception {
        install();
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
        UUID worker = UUID.randomUUID();
        connection.setAutoCommit(false);
        String first = value("SELECT event_id FROM omni_projection_claim('" + worker + "',30000)");
        try (Connection other = another()) {
            String second = scalar(other,
                    "SELECT event_id FROM omni_projection_claim('" + UUID.randomUUID() + "',30000)");
            assertNotEquals(first, second);
        }
        connection.commit();
        connection.setAutoCommit(true);
        assertThrows(SQLException.class, () -> value("SELECT omni_projection_fail("
                + first + ",'" + worker + "',999,'DB_RETRY',0)"));
        assertEquals("leased", value("SELECT state FROM omni_projection_job WHERE event_id=" + first));
        assertEquals("RETRY_SCHEDULED", value("SELECT omni_projection_fail("
                + first + ",'" + worker + "',1,'DB_RETRY',0)"));
    }

    @Test
    void expiredLeaseCanBeReclaimedAfterWorkerDisappears() throws Exception {
        install();
        UUID oldWorker = UUID.randomUUID();
        String event;
        try (Connection vanishedWorker = another()) {
            event = scalar(vanishedWorker, "SELECT event_id FROM omni_projection_claim('" + oldWorker + "',100)");
        }
        execute(connection, "SELECT pg_sleep(0.15)");
        UUID nextWorker = UUID.randomUUID();
        assertEquals("2", value("SELECT fence FROM omni_projection_claim('" + nextWorker + "',30000)"));
        assertThrows(SQLException.class, () -> value("SELECT omni_projection_fail("
                + event + ",'" + oldWorker + "',1,'DB_RETRY',0)"));
        assertEquals(nextWorker.toString(), value("SELECT owner FROM omni_projection_job WHERE event_id=" + event));
    }

    @Test
    void retryBudgetExhaustionStaysDurablyBlocked() throws Exception {
        install();
        UUID worker = UUID.randomUUID();
        for (int attempt = 1; attempt <= 5; attempt++) {
            String event = value("SELECT event_id FROM omni_projection_claim('" + worker + "',30000)");
            assertEquals(attempt == 5 ? "EXHAUSTED" : "RETRY_SCHEDULED",
                    value("SELECT omni_projection_fail(" + event + ",'" + worker + "',"
                            + attempt + ",'DB_RETRY',0)"));
        }
        assertEquals("0", value("SELECT count(*) FROM omni_projection_claim('" + worker + "',30000)"));
        assertEquals("BLOCKED_RETRY_EXHAUSTED", value("SELECT omni_patient_projection_read_status()"));
    }

    @Test
    void triggerTamperingAndTruncationFailClosed() throws Exception {
        install();
        assertThrows(SQLException.class, () -> execute(connection, "TRUNCATE hfj_res_ver"));
        assertThrows(SQLException.class, () -> execute(connection, "DELETE FROM omni_projection_event"));
        assertThrows(SQLException.class, () -> execute(connection, "DELETE FROM omni_projection_job"));
        execute(connection, "ALTER TABLE hfj_res_ver DISABLE TRIGGER omni_projection_capture");
        assertThrows(SQLException.class, () -> value("SELECT omni_patient_projection_read_status()"));
    }

    @Test
    void replicaModeStillCapturesAndJournalProtectionIsChecked() throws Exception {
        install();
        long baseline = count();
        execute(connection, "SET session_replication_role=replica");
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
        assertEquals(baseline + 1, count());
        assertEquals(Long.toString(baseline + 1), value("SELECT count(*) FROM omni_projection_job"));
        execute(connection, "SET session_replication_role=origin");
        execute(connection, "ALTER TABLE omni_projection_event DISABLE TRIGGER omni_projection_immutable");
        assertThrows(SQLException.class, () -> value("SELECT omni_patient_projection_read_status()"));
    }

    @Test
    void changedPrimaryKeyIsNotAcceptedAsTheSameCaptureContract() throws Exception {
        install();
        String primaryKey = value("""
                SELECT conname FROM pg_constraint WHERE conrelid='hfj_resource'::regclass AND contype='p'
                """);
        execute(connection, "ALTER TABLE hfj_resource DROP CONSTRAINT \"" + primaryKey + "\"");
        assertThrows(SQLException.class, () -> value("SELECT omni_patient_projection_read_status()"));
    }

    @Test
    void schemaDriftAndRepeatInstallationAreRejected() throws Exception {
        install();
        assertThrows(SQLException.class, this::install);
        execute(connection, "ROLLBACK");
        assertEquals("1", value("SELECT count(*) FROM omni_projection_migration"));
        execute(connection, "ALTER TABLE hfj_res_ver ADD COLUMN unsupported text");
        assertThrows(SQLException.class, () -> value("SELECT omni_patient_projection_read_status()"));
    }

    @Test
    void unsupportedInputMakesInstallationRollBackCompletely() throws Exception {
        execute(connection, "UPDATE hfj_resource SET partition_id=42 WHERE res_id=" + patient);
        assertThrows(SQLException.class, this::install);
        execute(connection, "ROLLBACK");
        assertNull(value("SELECT to_regclass('omni_projection_event')"));
        assertEquals("0", value("SELECT count(*) FROM pg_trigger WHERE tgrelid='hfj_resource'::regclass "
                + "AND tgname='omni_projection_capture'"));
    }

    @Test
    void installerDrainsAnExistingWriterBeforeBootstrap() throws Exception {
        connection.setAutoCommit(false);
        execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
        var executor = Executors.newSingleThreadExecutor();
        try (Connection installer = another()) {
            String installerPid = scalar(installer, "SELECT pg_backend_pid()");
            var result = executor.submit(() -> {
                execute(installer, migration());
                return true;
            });
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (!"true".equals(value(
                    "SELECT EXISTS(SELECT FROM pg_locks WHERE NOT granted AND pid=" + installerPid + ")"))) {
                assertTrue(System.nanoTime() < deadline, "Installer did not wait for the existing HAPI writer");
                Thread.sleep(25);
            }
            assertFalse(result.isDone());
            connection.commit();
            assertTrue(result.get(10, TimeUnit.SECONDS));
            connection.setAutoCommit(true);
            assertEquals("1", value("SELECT count(*) FROM omni_projection_event WHERE operation='BOOTSTRAP'"));
            execute(connection, "UPDATE hfj_resource SET res_ver=res_ver+1 WHERE res_id=" + patient);
            assertEquals("1", value("SELECT count(*) FROM omni_projection_event WHERE operation='UPDATE'"));
        } finally {
            if (!connection.getAutoCommit()) {
                connection.rollback();
                connection.setAutoCommit(true);
            }
            executor.shutdownNow();
        }
    }
}
