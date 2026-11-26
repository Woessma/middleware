package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.RequestTypeEnum;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.IPreResourceAccessDetails;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.server.provider.ProviderConstants;
import ca.uhn.fhir.rest.server.servlet.ServletSubRequestDetails;
import java.util.Objects;
import java.util.Set;
import org.springframework.transaction.support.TransactionCallback;

@Interceptor
public final class PatientProjectionReadInterceptor {
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

    public PatientProjectionReadInterceptor(ProjectionReadinessGate readinessGate, HapiTransactionService transactions) {
        this.readinessGate = Objects.requireNonNull(readinessGate);
        this.transactions = Objects.requireNonNull(transactions);
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
            requireReady();
        }
    }

    @Hook(Pointcut.STORAGE_PREACCESS_RESOURCES)
    public void beforeResourcesLeaveStorage(IPreResourceAccessDetails details, RequestDetails requestDetails) {
        boolean write = requestDetails != null
                && ((requestDetails.getRestOperationType() != null
                        && RESOURCE_WRITES.contains(requestDetails.getRestOperationType()))
                        || isNativeBundleWrite(requestDetails));
        for (int index = 0; index < details.size(); index++) {
            var resource = details.getResource(index);
            if (resource != null && "Patient".equals(resource.fhirType())) {
                if (write && !MdmResourceUtil.isGoldenRecord(resource)
                        && !MdmResourceUtil.isGoldenRecordRedirected(resource)) {
                    continue;
                }
                requireReady();
                return;
            }
        }
    }

    private void requireReady() {
        transactions.withSystemRequest().readOnly().execute((TransactionCallback<Void>) status -> {
            readinessGate.requireReady();
            return null;
        });
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
