package ch.omnilink.fhir.mdm.fixture;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.jpa.api.dao.DaoRegistry;
import ca.uhn.fhir.jpa.api.dao.IFhirResourceDao;
import ca.uhn.fhir.jpa.dao.tx.HapiTransactionService;
import ca.uhn.fhir.jpa.model.dao.JpaPid;
import ca.uhn.fhir.mdm.api.IMdmLinkUpdaterSvc;
import ca.uhn.fhir.mdm.api.IMdmControllerSvc;
import ca.uhn.fhir.mdm.api.IMdmLinkSvc;
import ca.uhn.fhir.mdm.api.MdmLinkSourceEnum;
import ca.uhn.fhir.mdm.api.MdmMatchOutcome;
import ca.uhn.fhir.mdm.api.MdmMatchResultEnum;
import ca.uhn.fhir.mdm.model.MdmCreateOrUpdateParams;
import ca.uhn.fhir.mdm.model.MdmMergeGoldenResourcesParams;
import ca.uhn.fhir.mdm.model.MdmTransactionContext;
import ca.uhn.fhir.rest.api.RestOperationTypeEnum;
import ca.uhn.fhir.rest.api.server.SystemRequestDetails;
import ca.uhn.fhir.rest.server.TransactionLogMessages;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector;
import ch.omnilink.fhir.mdm.extension.GoldenManualIdentifierPolicy;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Claim;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Result;
import ch.omnilink.fhir.mdm.extension.PatientIdentifierProjector.Recovery;
import ch.omnilink.fhir.mdm.extension.PatientProjectionWorker;
import jakarta.persistence.EntityManagerFactory;
import java.util.UUID;
import org.hibernate.Session;
import org.hl7.fhir.r4.model.Patient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.orm.jpa.EntityManagerFactoryUtils;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/__omni-projector-test")
@ConditionalOnProperty(name = "omnilink.mdm.projector-test-fixture", havingValue = "true")
public class ProjectorTestController {
    public record LinkCommand(long goldenPid, long sourcePid) {}
    public record MergeCommand(long fromPid, long toPid) {}
    private final PatientIdentifierProjector projector;
    private final HapiTransactionService transactions;
    private final IFhirResourceDao<Patient> patients;
    private final IMdmLinkUpdaterSvc updater;
    private final IMdmControllerSvc controller;
    private final IMdmLinkSvc linkService;
    private final ObjectProvider<PatientProjectionWorker> worker;

    public ProjectorTestController(PatientIdentifierProjector projector, HapiTransactionService transactions,
            DaoRegistry registry, IMdmLinkUpdaterSvc updater, EntityManagerFactory factory,
            ObjectProvider<PatientProjectionWorker> worker, IMdmControllerSvc controller,
            IMdmLinkSvc linkService) {
        this.projector = projector;
        this.transactions = transactions;
        this.patients = registry.getResourceDao(Patient.class);
        this.updater = updater;
        this.worker = worker;
        this.controller = controller;
        this.linkService = linkService;
        transactions.withSystemRequest().execute((TransactionCallback<Void>) status -> {
            var em = EntityManagerFactoryUtils.getTransactionalEntityManager(factory);
            if (em == null) {
                throw new IllegalStateException("Missing test fixture transaction");
            }
            em.unwrap(Session.class).doWork(connection -> {
                try (var sql = connection.createStatement();
                        var rows = sql.executeQuery("SELECT current_database()")) {
                    if (!rows.next() || !"mdm_outbox_test".equals(rows.getString(1))) {
                        throw new IllegalStateException("Test controller must never load against a lab database");
                    }
                }
            });
            return null;
        });
    }

    @PostMapping("/claim")
    public ResponseEntity<Claim> claim(@RequestParam("worker") UUID worker,
            @RequestParam(value = "lease", defaultValue = "30000") int lease) {
        return projector.claim(worker, lease).map(ResponseEntity::ok)
                .orElseGet(() -> ResponseEntity.noContent().build());
    }

    @PostMapping("/apply")
    public Result apply(@RequestBody Claim claim,
            @RequestParam(value = "loseResponse", defaultValue = "false") boolean loseResponse) {
        Result result = projector.apply(claim);
        if (loseResponse) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Synthetic lost post-commit response");
        }
        return result;
    }

    @PostMapping("/recover")
    public Recovery recover(@RequestBody Claim claim,
            @RequestParam(value = "delay", defaultValue = "5000") int delay,
            @RequestParam(value = "loseResponse", defaultValue = "false") boolean loseResponse) {
        Recovery result = projector.recover(claim, delay);
        if (loseResponse) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Synthetic lost recovery response");
        }
        return result;
    }

    @GetMapping("/worker")
    public ResponseEntity<PatientProjectionWorker.State> workerState() {
        PatientProjectionWorker running = worker.getIfAvailable();
        return running == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(running.state());
    }

    @GetMapping(value = "/patient/{pid}", produces = "application/fhir+json")
    public String patient(@PathVariable("pid") long pid) {
        return transactions.withSystemRequest().execute((TransactionCallback<String>) status ->
                FhirContext.forR4Cached().newJsonParser().encodeResourceToString(patients.readByPid(JpaPid.fromId(pid))));
    }

    @PostMapping("/native/{pid}")
    public void editNativeIdentifier(@PathVariable("pid") long pid,
            @RequestParam(value = "remove", defaultValue = "false") boolean remove) {
        transactions.withSystemRequest().execute((TransactionCallback<Void>) status -> {
            Patient patient = patients.readByPid(JpaPid.fromId(pid)).copy();
            if (remove) {
                patient.getIdentifier().removeIf(i -> "urn:synthetic:native".equals(i.getSystem()));
            } else {
                patient.addIdentifier().setSystem("urn:synthetic:native").setValue("native-" + pid);
            }
            var request = new SystemRequestDetails();
            request.setRestOperationType(RestOperationTypeEnum.UPDATE);
            request.getUserData().put(GoldenManualIdentifierPolicy.MANUAL_EDIT_CONTEXT, Boolean.TRUE);
            patients.update(patient, request);
            return null;
        });
    }

    @PostMapping("/duplicate")
    public void duplicate(@RequestBody LinkCommand command) {
        transactions.withSystemRequest().execute((TransactionCallback<Void>) status -> {
            Patient golden = patients.readByPid(JpaPid.fromId(command.goldenPid()));
            Patient other = patients.readByPid(JpaPid.fromId(command.sourcePid()));
            linkService.updateLink(golden, other,
                    new MdmMatchOutcome(null, null).setMatchResultEnum(MdmMatchResultEnum.POSSIBLE_DUPLICATE),
                    MdmLinkSourceEnum.AUTO, new MdmTransactionContext(
                            TransactionLogMessages.createFromTransactionGuid(UUID.randomUUID().toString()),
                            MdmTransactionContext.OperationType.DUPLICATE_GOLDEN_RESOURCES, "Patient"));
            return null;
        });
    }

    @PostMapping("/unlink")
    public void unlink(@RequestBody LinkCommand command) {
        transactions.withSystemRequest().execute((TransactionCallback<Void>) status -> {
            Patient golden = patients.readByPid(JpaPid.fromId(command.goldenPid()));
            Patient source = patients.readByPid(JpaPid.fromId(command.sourcePid()));
            var parameters = new MdmCreateOrUpdateParams();
            parameters.setGoldenResourceId(golden.getIdElement().toUnqualifiedVersionless().getValue());
            parameters.setGoldenResource(golden);
            parameters.setResourceId(source.getIdElement().toUnqualifiedVersionless().getValue());
            parameters.setSourceResource(source);
            parameters.setMatchResult(MdmMatchResultEnum.NO_MATCH);
            parameters.setMdmContext(new MdmTransactionContext(
                    TransactionLogMessages.createFromTransactionGuid(UUID.randomUUID().toString()),
                    MdmTransactionContext.OperationType.UPDATE_LINK, "Patient"));
            var request = new SystemRequestDetails();
            request.setRestOperationType(RestOperationTypeEnum.UPDATE);
            parameters.setRequestDetails(request);
            updater.updateLink(parameters);
            return null;
        });
    }

    @PostMapping("/merge")
    public void merge(@RequestBody MergeCommand command,
            @RequestParam(value = "manualPayload", defaultValue = "false") boolean manualPayload,
            @RequestParam(value = "failBeforeCommit", defaultValue = "false") boolean failBeforeCommit,
            @RequestParam(value = "loseResponse", defaultValue = "false") boolean loseResponse) {
        transactions.withSystemRequest().execute((TransactionCallback<Void>) status -> {
            Patient from = patients.readByPid(JpaPid.fromId(command.fromPid()));
            Patient to = patients.readByPid(JpaPid.fromId(command.toPid()));
            var parameters = new MdmMergeGoldenResourcesParams();
            parameters.setFromGoldenResource(from);
            parameters.setFromGoldenResourceId(from.getIdElement().getValue());
            parameters.setToGoldenResource(to);
            parameters.setToGoldenResourceId(to.getIdElement().getValue());
            if (manualPayload) {
                Patient merged = to.copy();
                merged.getIdentifier().clear();
                parameters.setManuallyMergedResource(merged);
            }
            parameters.setMdmTransactionContext(new MdmTransactionContext(
                    TransactionLogMessages.createFromTransactionGuid(UUID.randomUUID().toString()),
                    manualPayload ? MdmTransactionContext.OperationType.MANUAL_MERGE_GOLDEN_RESOURCES
                            : MdmTransactionContext.OperationType.MERGE_GOLDEN_RESOURCES, "Patient"));
            parameters.setRequestDetails(new SystemRequestDetails());
            controller.mergeGoldenResources(parameters);
            if (failBeforeCommit) {
                throw new IllegalStateException("Synthetic failure after native merge");
            }
            return null;
        });
        if (loseResponse) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Synthetic lost merge response");
        }
    }
}
