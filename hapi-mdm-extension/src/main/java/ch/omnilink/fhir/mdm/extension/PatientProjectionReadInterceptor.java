package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.batch2.api.IJobCoordinator;
import ca.uhn.fhir.batch2.model.JobInstance;
import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.jpa.model.util.JpaConstants;
import ca.uhn.fhir.jpa.searchparam.SearchParameterMap;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.Constants;
import ca.uhn.fhir.rest.api.RequestTypeEnum;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.bulk.BulkExportJobParameters;
import ca.uhn.fhir.rest.api.server.IPreResourceAccessDetails;
import ca.uhn.fhir.rest.api.server.IPreResourceShowDetails;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.server.exceptions.BaseServerResponseException;
import ca.uhn.fhir.rest.server.util.ICachedSearchDetails;
import ca.uhn.fhir.rest.server.provider.ProviderConstants;
import ca.uhn.fhir.rest.server.servlet.ServletSubRequestDetails;
import java.util.Objects;
import java.util.Set;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.Binary;
import org.hl7.fhir.r4.model.Parameters;
import org.springframework.transaction.support.TransactionCallback;

@Interceptor
public final class PatientProjectionReadInterceptor {
    private static final String REQUEST_GENERATION =
            PatientProjectionReadInterceptor.class.getName() + ".generation";
    private static final String EXPORT_GENERATION = "omnilink.patient-projection.generation";
    private static final String BINARY_GENERATION_SYSTEM = "urn:omnilink:mdm:projection-generation";
    private static final Set<RestOperationTypeEnum> PATIENT_READS = Set.of(
            RestOperationTypeEnum.READ,
            RestOperationTypeEnum.VREAD,
            RestOperationTypeEnum.SEARCH_TYPE,
            RestOperationTypeEnum.HISTORY_INSTANCE,
            RestOperationTypeEnum.HISTORY_TYPE,
            RestOperationTypeEnum.GET_TAGS,
            RestOperationTypeEnum.META);
    private static final Set<RestOperationTypeEnum> RESOURCE_WRITES = Set.of(
            RestOperationTypeEnum.CREATE,
            RestOperationTypeEnum.UPDATE,
            RestOperationTypeEnum.DELETE,
            RestOperationTypeEnum.PATCH,
            RestOperationTypeEnum.META_ADD,
            RestOperationTypeEnum.META_DELETE,
            RestOperationTypeEnum.ADD_TAGS,
            RestOperationTypeEnum.DELETE_TAGS,
            RestOperationTypeEnum.UPDATE_REWRITE_HISTORY);

    private final ProjectionReadinessGate readinessGate;
    private final HapiTransactionService transactions;
    private final IJobCoordinator jobs;

    public PatientProjectionReadInterceptor(
            ProjectionReadinessGate readinessGate, HapiTransactionService transactions, IJobCoordinator jobs) {
        this.readinessGate = Objects.requireNonNull(readinessGate);
        this.transactions = Objects.requireNonNull(transactions);
        this.jobs = Objects.requireNonNull(jobs);
    }

    @Hook(Pointcut.SERVER_INCOMING_REQUEST_PRE_HANDLED)
    public void beforePatientRead(RequestDetails requestDetails) {
        if (requestDetails == null) {
            return;
        }
        RestOperationTypeEnum operation = requestDetails.getRestOperationType();
        boolean patientRead = "Patient".equals(requestDetails.getResourceName())
                && operation != null && PATIENT_READS.contains(operation);
        boolean exportRead = requestDetails.getRequestType() != RequestTypeEnum.DELETE
                && (ProviderConstants.OPERATION_EXPORT.equals(requestDetails.getOperation())
                        || ProviderConstants.OPERATION_EXPORT_POLL_STATUS.equals(requestDetails.getOperation()));
        if (patientRead || operation == RestOperationTypeEnum.HISTORY_SYSTEM || exportRead) {
            requireReady(requestDetails);
        }
        String pageId = pageId(requestDetails);
        if (pageId != null) {
            requireSearchPageActive(requestDetails);
        }
        if (exportRead && ProviderConstants.OPERATION_EXPORT_POLL_STATUS.equals(requestDetails.getOperation())) {
            requireCurrentExport(requestDetails);
        }
    }

    @Hook(Pointcut.STORAGE_PRECHECK_FOR_CACHED_SEARCH)
    public boolean beforeCachedSearch(SearchParameterMap search, RequestDetails requestDetails) {
        if (requestDetails != null && !isWrite(requestDetails)
                && "Patient".equals(requestDetails.getResourceName())) {
            requireReady(requestDetails);
            return false;
        }
        return true;
    }

    @Hook(Pointcut.STORAGE_PRESEARCH_REGISTERED)
    public void beforeSearchRegistered(ICachedSearchDetails search, RequestDetails requestDetails) {
        if (requestDetails != null && !isWrite(requestDetails)
                && "Patient".equals(requestDetails.getResourceName())) {
            requireReady(requestDetails);
        }
    }

    @Hook(Pointcut.STORAGE_PREACCESS_RESOURCES)
    public void beforeResourcesLeaveStorage(IPreResourceAccessDetails details, RequestDetails requestDetails) {
        boolean write = isWrite(requestDetails);
        boolean patient = false;
        for (int index = 0; index < details.size(); index++) {
            var resource = details.getResource(index);
            if (resource == null) {
                continue;
            }
            if ("Patient".equals(resource.fhirType())
                    && (!write || MdmResourceUtil.isGoldenRecord(resource)
                            || MdmResourceUtil.isGoldenRecordRedirected(resource))) {
                patient = true;
            } else if (!write && resource instanceof Binary binary) {
                guardExportBinary(binary, requestDetails, true);
            }
        }
        if (patient || isSystemHistory(requestDetails) || pageId(requestDetails) != null) {
            requireReadyInCurrentTransaction(requestDetails);
            requireSearchPageActive(requestDetails);
        }
    }

    @Hook(Pointcut.STORAGE_PRESHOW_RESOURCES)
    public void beforeResourcesShown(IPreResourceShowDetails details, RequestDetails requestDetails) {
        boolean write = isWrite(requestDetails);
        boolean patient = false;
        for (IBaseResource resource : details) {
            if ("Patient".equals(resource.fhirType())
                    && (!write || MdmResourceUtil.isGoldenRecord(resource)
                            || MdmResourceUtil.isGoldenRecordRedirected(resource))) {
                patient = true;
            } else if (!write && resource instanceof Binary binary) {
                guardExportBinary(binary, requestDetails, false);
            }
        }
        if (patient || isPatientRead(requestDetails) || isSystemHistory(requestDetails)
                || pageId(requestDetails) != null) {
            requireReady(requestDetails);
            requireSearchPageActive(requestDetails);
        }
    }

    @Hook(Pointcut.STORAGE_INITIATE_BULK_EXPORT)
    public void bindBulkExportGeneration(BulkExportJobParameters parameters, RequestDetails requestDetails) {
        long generation = requireReady(requestDetails);
        String value = Long.toString(generation);
        parameters.setUserData(EXPORT_GENERATION, value);
        parameters.setBinarySecurityContextIdentifierSystem(BINARY_GENERATION_SYSTEM);
        parameters.setBinarySecurityContextIdentifierValue(value);
    }

    @Hook(Pointcut.STORAGE_BULK_EXPORT_RESOURCE_INCLUSION)
    public boolean requireCurrentBulkExportGeneration(
            BulkExportJobParameters parameters, IBaseResource resource) {
        long expectedGeneration = exportGeneration(parameters);
        long currentGeneration = transactions.withSystemRequest().readOnly().execute(
                (TransactionCallback<Long>) status -> readinessGate.requireReadyAndGetGeneration());
        if (expectedGeneration != currentGeneration) {
            throw BaseServerResponseException.newInstance(410, "Bulk export is stale for the current MDM generation");
        }
        return true;
    }

    private long requireReady(RequestDetails requestDetails) {
        if (requestDetails == null) {
            throw new IllegalStateException("Patient projection read has no request details");
        }
        long generation = transactions.withSystemRequest().readOnly().execute(
                (TransactionCallback<Long>) status -> readinessGate.requireReadyAndGetGeneration());
        return verifyAndRecordGeneration(requestDetails, generation);
    }

    private long requireReadyInCurrentTransaction(RequestDetails requestDetails) {
        if (requestDetails == null) {
            throw new IllegalStateException("Patient projection read has no request details");
        }
        return verifyAndRecordGeneration(requestDetails, readinessGate.requireReadyAndGetGeneration());
    }

    private static long verifyAndRecordGeneration(RequestDetails requestDetails, long generation) {
        Object existing = requestDetails.getUserData().putIfAbsent(REQUEST_GENERATION, generation);
        if (existing != null && (!(existing instanceof Number number) || number.longValue() != generation)) {
            throw BaseServerResponseException.newInstance(409, "FHIR response crossed an MDM generation change");
        }
        return generation;
    }

    private void requireSearchPageActive(RequestDetails requestDetails) {
        String pageId = pageId(requestDetails);
        if (pageId != null) {
            transactions.withSystemRequest().readOnly().execute((TransactionCallback<Void>) status -> {
                verifyGeneration(requestDetails, readinessGate.requireReadyAndGetGeneration());
                readinessGate.requireSearchActive(pageId);
                return null;
            });
        }
    }

    private static void verifyGeneration(RequestDetails requestDetails, long generation) {
        Object existing = requestDetails.getUserData().get(REQUEST_GENERATION);
        if (existing != null && (!(existing instanceof Number number) || number.longValue() != generation)) {
            throw BaseServerResponseException.newInstance(409, "FHIR response crossed an MDM generation change");
        }
        requestDetails.getUserData().putIfAbsent(REQUEST_GENERATION, generation);
    }

    private void requireCurrentExport(RequestDetails requestDetails) {
        String jobId = exportJobId(requestDetails);
        if (jobId == null) {
            return;
        }
        transactions.withSystemRequest().readOnly().execute((TransactionCallback<Void>) status -> {
            if (readinessGate.isLegacyExportJob(jobId)) {
                throw BaseServerResponseException.newInstance(410, "Legacy bulk export is no longer available");
            }
            JobInstance job = jobs.getInstance(jobId);
            long expectedGeneration = exportGeneration(job.getParameters(BulkExportJobParameters.class));
            long currentGeneration = readinessGate.requireReadyAndGetGeneration();
            if (expectedGeneration != currentGeneration) {
                throw BaseServerResponseException.newInstance(410, "Bulk export is stale for the current MDM generation");
            }
            return null;
        });
    }

    private void guardExportBinary(Binary binary, RequestDetails requestDetails, boolean currentTransaction) {
        if (!binary.hasSecurityContext() || !binary.getSecurityContext().hasIdentifier()
                || !BINARY_GENERATION_SYSTEM.equals(binary.getSecurityContext().getIdentifier().getSystem())) {
            boolean legacy;
            if (currentTransaction) {
                requireReadyInCurrentTransaction(requestDetails);
                legacy = readinessGate.isLegacyExportBinary(binary.getIdElement().getIdPart());
            } else {
                requireReady(requestDetails);
                legacy = transactions.withSystemRequest().readOnly().execute(
                        (TransactionCallback<Boolean>) status -> readinessGate.isLegacyExportBinary(
                                binary.getIdElement().getIdPart()));
            }
            if (legacy) {
                throw BaseServerResponseException.newInstance(410, "Legacy bulk export Binary is no longer available");
            }
            return;
        }
        long expected;
        try {
            expected = Long.parseLong(binary.getSecurityContext().getIdentifier().getValue());
        } catch (NumberFormatException exception) {
            throw BaseServerResponseException.newInstance(410, "Bulk export Binary has invalid generation metadata");
        }
        long current = currentTransaction
                ? requireReadyInCurrentTransaction(requestDetails)
                : requireReady(requestDetails);
        if (current != expected) {
            throw BaseServerResponseException.newInstance(410, "Bulk export Binary is stale for the current MDM generation");
        }
    }

    private static long exportGeneration(BulkExportJobParameters parameters) {
        Object generation = parameters.getUserData().get(EXPORT_GENERATION);
        if (generation instanceof Number number && number.longValue() >= 0) {
            return number.longValue();
        }
        if (generation instanceof String value) {
            try {
                long parsed = Long.parseLong(value);
                if (parsed >= 0) {
                    return parsed;
                }
            } catch (NumberFormatException ignored) {
                // Invalid persisted job data is rejected below.
            }
        }
        throw BaseServerResponseException.newInstance(410, "Bulk export has no valid MDM generation");
    }

    private static String exportJobId(RequestDetails requestDetails) {
        String[] values = requestDetails.getParameters().get(JpaConstants.PARAM_EXPORT_POLL_STATUS_JOB_ID);
        if (values != null && values.length > 0 && !values[0].isBlank()) {
            return values[0];
        }
        if (requestDetails.getResource() instanceof Parameters parameters) {
            return parameters.getParameter().stream()
                    .filter(parameter -> JpaConstants.PARAM_EXPORT_POLL_STATUS_JOB_ID.equals(parameter.getName()))
                    .map(parameter -> parameter.getValue().primitiveValue())
                    .filter(value -> value != null && !value.isBlank())
                    .findFirst()
                    .orElse(null);
        }
        return null;
    }

    private static String pageId(RequestDetails requestDetails) {
        if (requestDetails == null) {
            return null;
        }
        String[] values = requestDetails.getParameters().get(Constants.PARAM_PAGINGACTION);
        return values == null || values.length == 0 || values[0].isBlank() ? null : values[0];
    }

    private static boolean isPatientRead(RequestDetails requestDetails) {
        if (requestDetails == null) {
            return false;
        }
        RestOperationTypeEnum operation = requestDetails.getRestOperationType();
        return "Patient".equals(requestDetails.getResourceName())
                && operation != null && PATIENT_READS.contains(operation);
    }

    private static boolean isSystemHistory(RequestDetails requestDetails) {
        return requestDetails != null
                && requestDetails.getRestOperationType() == RestOperationTypeEnum.HISTORY_SYSTEM;
    }

    private static boolean isWrite(RequestDetails requestDetails) {
        return requestDetails != null
                && ((requestDetails.getRestOperationType() != null
                        && RESOURCE_WRITES.contains(requestDetails.getRestOperationType()))
                        || isNativeBundleWrite(requestDetails)
                        || isPatientCreateRequest(requestDetails)
                        || requestDetails.getFixedConditionalUrl() != null
                        || (requestDetails.getRequestType() == RequestTypeEnum.POST
                                && requestDetails.getHeader("If-None-Exist") != null));
    }

    private static boolean isPatientCreateRequest(RequestDetails requestDetails) {
        if (requestDetails.getRequestType() != RequestTypeEnum.POST
                || !"Patient".equals(requestDetails.getResourceName())) {
            return false;
        }
        String path = requestDetails.getRequestPath();
        return path != null && (path.equals("Patient") || path.equals("/Patient")
                || path.endsWith("/Patient"));
    }

    private static boolean isNativeBundleWrite(RequestDetails requestDetails) {
        // Native write entries inherit BATCH/TRANSACTION; embedded GETs receive their own read operation.
        if (!(requestDetails instanceof ServletSubRequestDetails)
                || (requestDetails.getRestOperationType() != RestOperationTypeEnum.BATCH
                        && requestDetails.getRestOperationType() != RestOperationTypeEnum.TRANSACTION)) {
            return false;
        }
        RequestTypeEnum method = requestDetails.getRequestType();
        return method == RequestTypeEnum.POST || method == RequestTypeEnum.PUT
                || method == RequestTypeEnum.PATCH || method == RequestTypeEnum.DELETE;
    }
}
