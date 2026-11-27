package ch.omnilink.fhir.mdm.fixture;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.IInterceptorService;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.rest.api.server.IPreResourceAccessDetails;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import jakarta.persistence.EntityManagerFactory;
import java.sql.Statement;
import java.util.Objects;
import org.hibernate.Session;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.orm.jpa.EntityManagerFactoryUtils;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Component
@Interceptor
@Order(Ordered.LOWEST_PRECEDENCE)
public final class ProjectionReaderLockProbeInterceptor implements SmartInitializingSingleton {
    private static final String HOLD_HEADER = "X-Omni-Test-Hold-Reader-Lock";

    private final EntityManagerFactory entityManagerFactory;
    private final IInterceptorService interceptorService;

    public ProjectionReaderLockProbeInterceptor(
            EntityManagerFactory entityManagerFactory, IInterceptorService interceptorService) {
        this.entityManagerFactory = Objects.requireNonNull(entityManagerFactory);
        this.interceptorService = Objects.requireNonNull(interceptorService);
    }

    @Override
    public void afterSingletonsInstantiated() {
        if (!interceptorService.registerInterceptor(this)) {
            throw new IllegalStateException("Cannot register the reader-lock test probe");
        }
    }

    @Hook(Pointcut.STORAGE_PREACCESS_RESOURCES)
    public void pauseAfterPatientRead(IPreResourceAccessDetails details, RequestDetails requestDetails) {
        if (requestDetails == null || !"true".equals(requestDetails.getHeader(HOLD_HEADER))) {
            return;
        }
        boolean hasPatient = false;
        for (int index = 0; index < details.size(); index++) {
            if (details.getResource(index) != null && "Patient".equals(details.getResource(index).fhirType())) {
                hasPatient = true;
                break;
            }
        }
        if (!hasPatient) {
            return;
        }
        if (!TransactionSynchronizationManager.isActualTransactionActive()) {
            throw new IllegalStateException("Reader lock probe is outside the HAPI storage transaction");
        }
        var entityManager = EntityManagerFactoryUtils.getTransactionalEntityManager(entityManagerFactory);
        if (entityManager == null) {
            throw new IllegalStateException("Reader lock probe has no bound EntityManager");
        }
        entityManager.unwrap(Session.class).doWork(connection -> {
            try (Statement statement = connection.createStatement()) {
                statement.execute("SELECT set_config('application_name', 'omni-reader-lock-probe', true)");
                statement.execute("SELECT pg_sleep(5)");
            }
        });
    }
}
