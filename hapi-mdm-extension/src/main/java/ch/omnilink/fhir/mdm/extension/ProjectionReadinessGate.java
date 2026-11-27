package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.rest.server.exceptions.BaseServerResponseException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Objects;
import org.hibernate.Session;
import org.springframework.orm.jpa.EntityManagerFactoryUtils;
import org.springframework.transaction.support.TransactionSynchronizationManager;

public final class ProjectionReadinessGate {
    private static final String READ_STATUS_SQL = "SELECT omni_patient_projection_read_status()";
    private static final String READER_PROTOCOL_SQL =
            "SELECT to_regprocedure('omni_projection_acquire_reader_lock()') IS NOT NULL";
    private static final String ACQUIRE_READER_LOCK_SQL = "SELECT omni_projection_acquire_reader_lock()";

    private final EntityManagerFactory entityManagerFactory;

    public ProjectionReadinessGate(EntityManagerFactory entityManagerFactory) {
        this.entityManagerFactory = Objects.requireNonNull(entityManagerFactory);
    }

    public void requireReady() {
        requireReadyAndGetGeneration();
    }

    public long requireReadyAndGetGeneration() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Patient projection status check is outside a transaction");
        }
        EntityManager entityManager =
                EntityManagerFactoryUtils.getTransactionalEntityManager(entityManagerFactory);
        if (entityManager == null) {
            throw new IllegalStateException("Patient projection status check has no bound EntityManager");
        }
        String[] status = {null};
        long[] generation = {-1};
        entityManager.unwrap(Session.class).doWork(connection -> {
            try (Statement statement = connection.createStatement();
                    var rows = statement.executeQuery(READER_PROTOCOL_SQL)) {
                if (!rows.next()) {
                    throw new SQLException("Patient reader protocol check returned no row");
                }
                if (rows.getBoolean(1)) {
                    try (var lock = connection.createStatement();
                            var lockedRows = lock.executeQuery(ACQUIRE_READER_LOCK_SQL)) {
                        if (!lockedRows.next()) {
                            throw new SQLException("Patient reader lock returned no generation");
                        }
                        generation[0] = lockedRows.getLong(1);
                    }
                }
            }
            try (Statement statement = connection.createStatement();
                    var rows = statement.executeQuery(READ_STATUS_SQL)) {
                if (!rows.next()) {
                    throw new SQLException("Patient projection status returned no row");
                }
                status[0] = rows.getString(1);
            }
        });
        if (!"READY".equals(status[0])) {
            throw BaseServerResponseException.newInstance(503, "MDM patient projection is not ready");
        }
        if (generation[0] < 0) {
            throw new IllegalStateException("Patient projection reported READY without the reader protocol");
        }
        return generation[0];
    }

    public void requireSearchActive(String searchUuid) {
        if (searchUuid == null || searchUuid.isBlank()) {
            throw BaseServerResponseException.newInstance(410, "FHIR search page is no longer available");
        }
        EntityManager entityManager =
                EntityManagerFactoryUtils.getTransactionalEntityManager(entityManagerFactory);
        if (entityManager == null || !TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("FHIR search cache check is outside a transaction");
        }
        boolean[] active = {false};
        entityManager.unwrap(Session.class).doWork(connection -> {
            try (var statement = connection.prepareStatement(
                            "SELECT search_deleted FROM hfj_search WHERE search_uuid = ?")) {
                statement.setString(1, searchUuid);
                try (var rows = statement.executeQuery()) {
                    active[0] = rows.next() && !rows.getBoolean(1);
                }
            }
        });
        if (!active[0]) {
            throw BaseServerResponseException.newInstance(410, "FHIR search page is no longer available");
        }
    }

    public boolean isLegacyExportJob(String jobId) {
        return queryBoolean("SELECT omni_projection_is_legacy_export_job(?)", jobId);
    }

    public boolean isLegacyExportBinary(String binaryId) {
        return queryBoolean("SELECT omni_projection_is_legacy_export_binary(?)", binaryId);
    }

    private boolean queryBoolean(String sql, String value) {
        EntityManager entityManager =
                EntityManagerFactoryUtils.getTransactionalEntityManager(entityManagerFactory);
        if (entityManager == null || !TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Legacy export check is outside a transaction");
        }
        boolean[] result = {false};
        entityManager.unwrap(Session.class).doWork(connection -> {
            try (var statement = connection.prepareStatement(sql)) {
                statement.setString(1, value);
                try (var rows = statement.executeQuery()) {
                    if (!rows.next()) {
                        throw new SQLException("Legacy export check returned no row");
                    }
                    result[0] = rows.getBoolean(1);
                }
            }
        });
        return result[0];
    }
}
