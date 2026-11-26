package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.interceptor.api.Hook;
import ca.uhn.fhir.interceptor.api.Interceptor;
import ca.uhn.fhir.interceptor.api.Pointcut;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.server.RequestDetails;
import ca.uhn.fhir.rest.api.server.SystemRequestDetails;
import ca.uhn.fhir.rest.server.exceptions.InvalidRequestException;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.Patient;

@Interceptor
public final class GoldenManualIdentifierInterceptor {
    @Hook(Pointcut.STORAGE_PRESTORAGE_RESOURCE_CREATED)
    public void rejectNewManualOwnership(IBaseResource incoming) {
        if (incoming instanceof Patient patient && patient.getIdentifier().stream()
                .anyMatch(i -> !i.getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).isEmpty())) {
            throw new InvalidRequestException("Manual ownership requires an explicit edit of an existing Golden");
        }
    }

    @Hook(Pointcut.STORAGE_PRESTORAGE_RESOURCE_UPDATED)
    public void preserveManualGoldenIdentifiers(
            IBaseResource previous, IBaseResource incoming, RequestDetails requestDetails) {
        if (previous instanceof Patient old && incoming instanceof Patient updated
                && requestDetails instanceof SystemRequestDetails
                && GoldenManualIdentifierPolicy.reconcileMerge(old, updated)) {
            return;
        }
        if (incoming instanceof Patient patient && MdmResourceUtil.isGoldenRecord(patient)
                && !(previous instanceof Patient)) {
            throw new InvalidRequestException("Golden identifier policy requires the previous resource snapshot");
        }
        boolean manualRequest = requestDetails instanceof SystemRequestDetails
                && Boolean.TRUE.equals(requestDetails.getUserData()
                        .get(GoldenManualIdentifierPolicy.MANUAL_EDIT_CONTEXT));
        if (manualRequest && (!(previous instanceof Patient old) || !MdmResourceUtil.isGoldenRecord(old)
                || !(incoming instanceof Patient updated) || !MdmResourceUtil.isGoldenRecord(updated))) {
            throw new InvalidRequestException("Manual identifier edit requires old and new Golden snapshots");
        }
        if (incoming instanceof Patient patient && !MdmResourceUtil.isGoldenRecord(patient)) {
            rejectNewManualOwnership(patient);
        }
        if (!(previous instanceof Patient oldPatient) || !(incoming instanceof Patient newPatient)
                || !MdmResourceUtil.isGoldenRecord(oldPatient) || !MdmResourceUtil.isGoldenRecord(newPatient)
                || MdmResourceUtil.isGoldenRecordRedirected(newPatient)) {
            return;
        }
        newPatient.setIdentifier(GoldenManualIdentifierPolicy.reconcile(oldPatient, newPatient, manualRequest)
                .getIdentifier());
    }
}
