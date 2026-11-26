package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.jpa.api.dao.DaoRegistry;
import ca.uhn.fhir.jpa.api.dao.IFhirResourceDao;
import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.mdm.api.IGoldenResourceMergerSvc;
import ca.uhn.fhir.mdm.model.MdmMergeGoldenResourcesParams;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.server.SystemRequestDetails;
import ca.uhn.fhir.rest.server.exceptions.InvalidRequestException;
import ca.uhn.fhir.rest.server.exceptions.ResourceVersionConflictException;
import org.hl7.fhir.instance.model.api.IAnyResource;
import org.hl7.fhir.r4.model.Patient;
import org.springframework.transaction.support.TransactionCallback;

public final class GoldenPatientMergeService implements IGoldenResourceMergerSvc {
    private final IGoldenResourceMergerSvc delegate;
    private final HapiTransactionService transactions;
    private final IFhirResourceDao<Patient> patients;

    public GoldenPatientMergeService(IGoldenResourceMergerSvc delegate,
            HapiTransactionService transactions, DaoRegistry registry) {
        this.delegate = delegate;
        this.transactions = transactions;
        this.patients = registry.getResourceDao(Patient.class);
    }

    @Override
    public IAnyResource mergeGoldenResources(MdmMergeGoldenResourcesParams parameters) {
        if (!(parameters.getFromGoldenResource() instanceof Patient from)
                || !(parameters.getToGoldenResource() instanceof Patient to)) {
            return delegate.mergeGoldenResources(parameters);
        }
        return transactions.withSystemRequest().execute((TransactionCallback<IAnyResource>) status -> {
            Patient storedFrom = currentGolden(from);
            Patient storedTo = currentGolden(to);
            return GoldenManualIdentifierPolicy.duringMerge(storedFrom, storedTo,
                    () -> delegate.mergeGoldenResources(parameters));
        });
    }

    private Patient currentGolden(Patient supplied) {
        if (!supplied.getIdElement().hasIdPart() || !supplied.getIdElement().hasVersionIdPart()) {
            throw new InvalidRequestException("Golden merge requires versioned Patient snapshots");
        }
        Patient stored = patients.read(supplied.getIdElement().toUnqualifiedVersionless(), new SystemRequestDetails());
        if (!MdmResourceUtil.isGoldenRecord(stored) || MdmResourceUtil.isGoldenRecordRedirected(stored)) {
            throw new InvalidRequestException("Golden merge requires two active Golden Patients");
        }
        if (!stored.getIdElement().getVersionIdPart().equals(supplied.getIdElement().getVersionIdPart())) {
            throw new ResourceVersionConflictException("Golden merge snapshot is no longer current");
        }
        return stored.copy();
    }
}
