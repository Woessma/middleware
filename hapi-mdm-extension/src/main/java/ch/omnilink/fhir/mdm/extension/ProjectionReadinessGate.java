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

    private final EntityManagerFactory entityManagerFactory;

    public ProjectionReadinessGate(EntityManagerFactory entityManagerFactory) {
        this.entityManagerFactory = Objects.requireNonNull(entityManagerFactory);
    }

    public void requireReady() {
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Patient projection status check is outside a transaction");
        }
        EntityManager entityManager =
                EntityManagerFactoryUtils.getTransactionalEntityManager(entityManagerFactory);
        if (entityManager == null) {
            throw new IllegalStateException("Patient projection status check has no bound EntityManager");
        }
        String[] result = {null};
        entityManager.unwrap(Session.class).doWork(connection -> {
            try (Statement statement = connection.createStatement();
                    var rows = statement.executeQuery(READ_STATUS_SQL)) {
                if (!rows.next()) {
                    throw new SQLException("Patient projection status returned no row");
                }
                result[0] = rows.getString(1);
            }
        });
        if (!"READY".equals(result[0])) {
            throw BaseServerResponseException.newInstance(503, "MDM patient projection is not ready");
        }
    }
}
