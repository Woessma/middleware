package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.batch2.api.IJobCoordinator;
import ca.uhn.fhir.interceptor.api.IInterceptorService;
import ca.uhn.fhir.jpa.model.dao.JpaPid;
import ca.uhn.fhir.mdm.api.IMdmControllerSvc;
import ca.uhn.fhir.mdm.api.IGoldenResourceMergerSvc;
import ca.uhn.fhir.mdm.svc.IBulkExportMdmEidMatchOnlyResourceExpander;
import ca.uhn.fhir.mdm.svc.IBulkExportMdmFullResourceExpander;
import javax.sql.DataSource;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.scheduling.annotation.EnableScheduling;

import java.lang.reflect.Proxy;
import java.util.Set;

@Configuration
public class MdmProjectionExtensionConfiguration {
    @Configuration(proxyBeanMethods = false)
    @EnableScheduling
    @ConditionalOnProperty(name = "omnilink.mdm.projection.worker.enabled", havingValue = "true")
    static class WorkerConfiguration {
        @Bean
        PatientProjectionWorker patientProjectionWorker(PatientIdentifierProjector projector) {
            return new PatientProjectionWorker(projector);
        }
    }

    private static final Set<String> GUARDED_CONTROLLER_READS = Set.of(
            "queryLinks",
            "queryLinksFromPartitionList",
            "queryLinkHistory",
            "getDuplicateGoldenResources");
    private static final Set<String> GUARDED_BULK_EXPORT_READS = Set.of("expandGroup", "expandPatient");

    @Bean
    @Primary
    @ConditionalOnProperty(name = "omnilink.mdm.projection.enabled", havingValue = "true")
    AtomicMergeMdmLinkDaoSvc atomicMergeMdmLinkDaoSvc(
            @Qualifier("mdmLinkDaoSvc")
                    ca.uhn.fhir.jpa.mdm.dao.MdmLinkDaoSvc<JpaPid, ca.uhn.fhir.jpa.entity.MdmLink> delegate) {
        return new AtomicMergeMdmLinkDaoSvc(delegate);
    }

    @Bean
    @Primary
    @ConditionalOnProperty(name = "omnilink.mdm.projection.enabled", havingValue = "true")
    IGoldenResourceMergerSvc protectedGoldenPatientMergeService(
            @Qualifier("mdmGoldenResourceMergerSvc") IGoldenResourceMergerSvc delegate,
            HapiTransactionService transactions,
            ca.uhn.fhir.jpa.api.dao.DaoRegistry registry) {
        return new GoldenPatientMergeService(delegate, transactions, registry);
    }

    @Bean
    @ConditionalOnProperty(name = "omnilink.mdm.projection.enabled", havingValue = "true")
    PatientIdentifierProjector patientIdentifierProjector(
            HapiTransactionService transactions,
            jakarta.persistence.EntityManagerFactory factory,
            ca.uhn.fhir.jpa.api.dao.DaoRegistry registry,
            ca.uhn.fhir.mdm.api.IMdmLinkQuerySvc links) {
        return new PatientIdentifierProjector(transactions, factory, registry, links);
    }

    @Bean
    @ConditionalOnProperty(name = "omnilink.mdm.projection.enabled", havingValue = "true")
    SmartInitializingSingleton registerGoldenManualIdentifierPolicy(IInterceptorService interceptors) {
        return () -> {
            if (!interceptors.registerInterceptor(new GoldenManualIdentifierInterceptor())) {
                throw new IllegalStateException("Cannot register global Golden manual identifier policy");
            }
        };
    }

    @Bean
    ProjectionReadinessGate projectionReadinessGate(jakarta.persistence.EntityManagerFactory entityManagerFactory) {
        return new ProjectionReadinessGate(entityManagerFactory);
    }

    @Bean
    PatientProjectionReadInterceptor patientProjectionReadInterceptor(
            ProjectionReadinessGate readinessGate, HapiTransactionService transactions, IJobCoordinator jobs) {
        return new PatientProjectionReadInterceptor(readinessGate, transactions, jobs);
    }

    @Bean
    @ConditionalOnProperty(name = "omnilink.mdm.projection.enabled", havingValue = "true")
    FilterRegistrationBean<ProjectionReadLockFilter> projectionReadLockFilter(DataSource dataSource) {
        var registration = new FilterRegistrationBean<>(new ProjectionReadLockFilter(dataSource));
        registration.setName("patientProjectionReadLockFilter");
        registration.addUrlPatterns("/fhir", "/fhir/*");
        return registration;
    }

    @Bean
    @Primary
    IMdmControllerSvc guardedMdmControllerSvc(
            @Qualifier("mdmControllerSvc") IMdmControllerSvc delegate,
            HapiTransactionService transactionService,
            ProjectionReadinessGate readinessGate) {
        return createGuardedProxy(
                IMdmControllerSvc.class,
                delegate,
                GUARDED_CONTROLLER_READS,
                "GuardedMdmControllerSvc",
                transactionService,
                readinessGate);
    }

    @Bean
    @Primary
    @SuppressWarnings("unchecked")
    IBulkExportMdmFullResourceExpander<JpaPid> guardedBulkExportMdmFullResourceExpander(
            @Qualifier("bulkExportMDMResourceExpander")
                    IBulkExportMdmFullResourceExpander<JpaPid> delegate,
            HapiTransactionService transactionService,
            ProjectionReadinessGate readinessGate) {
        return createGuardedProxy(
                IBulkExportMdmFullResourceExpander.class,
                delegate,
                GUARDED_BULK_EXPORT_READS,
                "GuardedBulkExportMdmFullResourceExpander",
                transactionService,
                readinessGate);
    }

    @Bean
    @Primary
    @SuppressWarnings("unchecked")
    IBulkExportMdmEidMatchOnlyResourceExpander<JpaPid> guardedBulkExportMdmEidMatchOnlyResourceExpander(
            @Qualifier("bulkExportMDMEidMatchOnlyResourceExpander")
                    IBulkExportMdmEidMatchOnlyResourceExpander<JpaPid> delegate,
            HapiTransactionService transactionService,
            ProjectionReadinessGate readinessGate) {
        return createGuardedProxy(
                IBulkExportMdmEidMatchOnlyResourceExpander.class,
                delegate,
                GUARDED_BULK_EXPORT_READS,
                "GuardedBulkExportMdmEidMatchOnlyResourceExpander",
                transactionService,
                readinessGate);
    }

    private static <T> T createGuardedProxy(
            Class<T> serviceType,
            T delegate,
            Set<String> guardedMethods,
            String proxyDescription,
            HapiTransactionService transactionService,
            ProjectionReadinessGate readinessGate) {
        return serviceType.cast(Proxy.newProxyInstance(
                serviceType.getClassLoader(),
                new Class<?>[] {serviceType},
                (proxy, method, args) -> {
                    if (method.getDeclaringClass() == Object.class) {
                        return switch (method.getName()) {
                            case "equals" -> proxy == args[0];
                            case "hashCode" -> System.identityHashCode(proxy);
                            case "toString" -> proxyDescription;
                            default -> throw new IllegalStateException("Unexpected Object method: " + method.getName());
                        };
                    }
                    if (!guardedMethods.contains(method.getName())) {
                        return invokeDelegate(delegate, method, args);
                    }
                    return transactionService.withSystemRequest().readOnly().execute(
                            (TransactionCallback<Object>) transactionStatus -> {
                                readinessGate.requireReady();
                                return invokeDelegate(delegate, method, args);
                            });
                }));
    }

    private static Object invokeDelegate(Object delegate, java.lang.reflect.Method method, Object[] args) {
        try {
            return method.invoke(delegate, args);
        } catch (java.lang.reflect.InvocationTargetException exception) {
            Throwable cause = exception.getCause();
            if (cause instanceof RuntimeException runtimeException) {
                throw runtimeException;
            }
            if (cause instanceof Error error) {
                throw error;
            }
            throw new IllegalStateException("MDM operation failed", cause);
        } catch (IllegalAccessException exception) {
            throw new IllegalStateException("Cannot invoke MDM operation", exception);
        }
    }
}
