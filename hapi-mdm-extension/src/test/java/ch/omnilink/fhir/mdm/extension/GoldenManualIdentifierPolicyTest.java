package ch.omnilink.fhir.mdm.extension;

import static org.junit.jupiter.api.Assertions.*;

import ca.uhn.fhir.rest.server.exceptions.InvalidRequestException;
import ca.uhn.fhir.mdm.api.MdmConstants;
import org.hl7.fhir.r4.model.BooleanType;
import org.hl7.fhir.r4.model.Identifier;
import org.hl7.fhir.r4.model.Patient;
import org.hl7.fhir.r4.model.Reference;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.rest.api.server.SystemRequestDetails;
import java.util.List;
import org.junit.jupiter.api.Test;

class GoldenManualIdentifierPolicyTest {
    @Test
    void marksNewManualKeysWithoutAdoptingExistingOrProjectedIdentifiers() {
        Patient previous = new Patient();
        previous.addIdentifier().setSystem("urn:existing").setValue("legacy");
        Patient incoming = previous.copy();
        incoming.addIdentifier().setSystem("urn:manual").setValue("new");
        Identifier projected = incoming.addIdentifier().setSystem("urn:source").setValue("derived");
        projected.addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        Patient result = GoldenManualIdentifierPolicy.reconcile(previous, incoming, true);
        assertTrue(result.getIdentifier().get(0).getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).isEmpty());
        assertEquals(1, result.getIdentifier().get(1).getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).size());
        assertTrue(result.getIdentifier().get(2).getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).isEmpty());
        assertTrue(incoming.getIdentifier().get(1).getExtension().isEmpty());
    }

    @Test
    void internalRebuildRestoresManualMetadataButNotRemovedSourceOrLegacyKeys() {
        Patient previous = manual();
        previous.getIdentifierFirstRep().setUse(Identifier.IdentifierUse.OFFICIAL);
        previous.addIdentifier().setSystem("urn:legacy").setValue("unclassified");
        previous.addIdentifier().setSystem("urn:source").setValue("derived")
                .addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        Patient rebuilt = new Patient();
        rebuilt.addIdentifier().setSystem("urn:manual").setValue("kept");
        Patient result = GoldenManualIdentifierPolicy.reconcile(previous, rebuilt, false);
        assertEquals(1, result.getIdentifier().size());
        assertTrue(previous.getIdentifierFirstRep().equalsDeep(result.getIdentifierFirstRep()));
        assertTrue(result.equalsDeep(GoldenManualIdentifierPolicy.reconcile(result, result, false)));
        assertEquals(1, GoldenManualIdentifierPolicy.reconcile(previous, new Patient(), false).getIdentifier().size());
    }

    @Test
    void explicitManualDeletionAndReplacementAreRespected() {
        Patient previous = manual();
        assertTrue(GoldenManualIdentifierPolicy.reconcile(previous, new Patient(), true).getIdentifier().isEmpty());
        Patient changed = previous.copy();
        changed.getIdentifierFirstRep().setValue("replacement").getExtension().clear();
        Patient result = GoldenManualIdentifierPolicy.reconcile(previous, changed, true);
        assertEquals("replacement", result.getIdentifierFirstRep().getValue());
        assertEquals(1, result.getIdentifierFirstRep().getExtensionsByUrl(GoldenManualIdentifierPolicy.MANUAL).size());
    }

    @Test
    void invalidOrConflictingOwnershipIsRejectedWithoutMutatingInputs() {
        Patient bad = manual();
        bad.getIdentifierFirstRep().addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        Patient original = bad.copy();
        assertThrows(InvalidRequestException.class,
                () -> GoldenManualIdentifierPolicy.reconcile(new Patient(), bad, true));
        assertTrue(original.equalsDeep(bad));
        Patient duplicate = manual();
        duplicate.addIdentifier(duplicate.getIdentifierFirstRep().copy());
        assertThrows(InvalidRequestException.class,
                () -> GoldenManualIdentifierPolicy.reconcile(new Patient(), duplicate, true));
        assertThrows(InvalidRequestException.class,
                () -> GoldenManualIdentifierPolicy.reconcile(new Patient(), manual(), false));
        Patient incomplete = new Patient();
        incomplete.addIdentifier().setValue("missing-system");
        assertThrows(InvalidRequestException.class,
                () -> GoldenManualIdentifierPolicy.reconcile(new Patient(), incomplete, true));
    }

    @Test
    void sourceOwnershipAndMissingOldGoldenSnapshotsAreRejected() {
        var interceptor = new GoldenManualIdentifierInterceptor();
        assertThrows(InvalidRequestException.class, () -> interceptor.rejectNewManualOwnership(manual()));
        assertThrows(InvalidRequestException.class,
                () -> interceptor.preserveManualGoldenIdentifiers(new Patient(), manual(), null));
        Patient golden = new Patient();
        golden.getMeta().addTag().setSystem(MdmConstants.SYSTEM_GOLDEN_RECORD_STATUS)
                .setCode(MdmConstants.CODE_GOLDEN_RECORD);
        assertThrows(InvalidRequestException.class,
                () -> interceptor.preserveManualGoldenIdentifiers(null, golden, null));
    }

    @Test
    void mergeTransfersOnlyExistingManualOwnershipAndCleansUpAfterFailure() {
        Patient from = manual();
        from.setId("Patient/from/_history/1");
        from.getMeta().addTag().setSystem(MdmConstants.SYSTEM_GOLDEN_RECORD_STATUS)
                .setCode(MdmConstants.CODE_GOLDEN_RECORD);
        Patient to = new Patient();
        to.setId("Patient/to/_history/2");
        to.getMeta().addTag().setSystem(MdmConstants.SYSTEM_GOLDEN_RECORD_STATUS)
                .setCode(MdmConstants.CODE_GOLDEN_RECORD);
        Patient storedFrom = from.copy();
        Patient storedTo = to.copy();
        var interceptor = new GoldenManualIdentifierInterceptor();
        assertThrows(IllegalStateException.class, () -> GoldenManualIdentifierPolicy.duringMerge(
                storedFrom, storedTo, () -> {
                    to.addIdentifier(from.getIdentifierFirstRep().copy());
                    interceptor.preserveManualGoldenIdentifiers(storedTo, to, new SystemRequestDetails());
                    assertEquals(1, to.getIdentifier().size());
                    Patient untagged = storedFrom.copy();
                    untagged.getMeta().getTag().clear();
                    interceptor.preserveManualGoldenIdentifiers(storedFrom, untagged, new SystemRequestDetails());
                    untagged.setActive(true);
                    assertThrows(InvalidRequestException.class, () -> interceptor.preserveManualGoldenIdentifiers(
                            storedFrom, untagged, new SystemRequestDetails()));
                    MdmResourceUtil.setGoldenResourceRedirected(from);
                    interceptor.preserveManualGoldenIdentifiers(storedFrom, from, new SystemRequestDetails());
                    assertEquals(1, from.getIdentifier().size());
                    throw new IllegalStateException("Synthetic failed merge");
                }));
        assertThrows(InvalidRequestException.class, () ->
                interceptor.preserveManualGoldenIdentifiers(storedTo, to, new SystemRequestDetails()));
    }

    @Test
    void mergeRejectsManualConflictsBeforeDelegatingOrAdoptingUnclassifiedKeys() {
        Patient from = manual();
        from.setId("Patient/from/_history/1");
        Patient to = manual();
        to.setId("Patient/to/_history/1");
        to.getIdentifierFirstRep().setUse(Identifier.IdentifierUse.OFFICIAL);
        for (boolean classified : List.of(true, false)) {
            if (!classified) {
                to.getIdentifierFirstRep().getExtension().clear();
            }
            assertThrows(InvalidRequestException.class, () -> GoldenManualIdentifierPolicy.duringMerge(
                    from.copy(), to.copy(), () -> {
                        fail("Conflicting ownership must be rejected before native writes");
                        return null;
                    }));
        }
    }

    @Test
    void mergeScopeCannotAuthorizeAnotherPatientOrInventManualKeys() {
        Patient from = manual();
        from.setId("Patient/from/_history/1");
        Patient to = new Patient();
        to.setId("Patient/to/_history/1");
        to.getMeta().addTag().setSystem(MdmConstants.SYSTEM_GOLDEN_RECORD_STATUS)
                .setCode(MdmConstants.CODE_GOLDEN_RECORD);
        Patient previous = to.copy();
        GoldenManualIdentifierPolicy.duringMerge(from.copy(), previous, () -> {
            to.setId("Patient/other/_history/1");
            assertFalse(GoldenManualIdentifierPolicy.reconcileMerge(previous, to));
            to.setId("Patient/to/_history/1");
            to.addIdentifier(from.getIdentifierFirstRep().copy().setValue("invented"));
            assertThrows(InvalidRequestException.class, () ->
                    GoldenManualIdentifierPolicy.reconcileMerge(previous, to));
            return null;
        });
    }

    @Test
    void mergedManagedKeysUnionProvenanceWithoutChangingMetadataOrInputs() {
        Identifier first = new Identifier().setSystem("urn:shared").setValue("shared");
        first.addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        first.addExtension(GoldenIdentifierReconciler.SOURCE, new Reference("Patient/one"));
        Identifier second = first.copy();
        second.getExtension().removeIf(e -> GoldenIdentifierReconciler.SOURCE.equals(e.getUrl()));
        second.addExtension(GoldenIdentifierReconciler.SOURCE, new Reference("Patient/two"));
        var result = GoldenIdentifierReconciler.normalizeMergedIdentifiers(List.of(first, second, first.copy()));
        assertEquals(1, result.size());
        assertEquals(List.of("Patient/one", "Patient/two"), result.get(0)
                .getExtensionsByUrl(GoldenIdentifierReconciler.SOURCE).stream()
                .map(e -> ((Reference) e.getValue()).getReference()).toList());
        assertEquals(1, first.getExtensionsByUrl(GoldenIdentifierReconciler.SOURCE).size());
        second.setUse(Identifier.IdentifierUse.OFFICIAL);
        assertThrows(IllegalArgumentException.class,
                () -> GoldenIdentifierReconciler.normalizeMergedIdentifiers(List.of(first, second)));
    }

    @Test
    void rebuildKeepsKnownManagedOwnershipWithoutAdoptingLegacyOrPromotingSources() {
        Patient previous = new Patient();
        Identifier projected = previous.addIdentifier().setSystem("urn:source").setValue("shared");
        projected.addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        projected.addExtension(GoldenIdentifierReconciler.SOURCE, new Reference("Patient/one"));
        previous.addIdentifier().setSystem("urn:legacy").setValue("unclassified");
        Patient rebuilt = new Patient();
        rebuilt.addIdentifier().setSystem("urn:source").setValue("shared");
        rebuilt.addIdentifier().setSystem("urn:legacy").setValue("unclassified");
        Patient result = GoldenManualIdentifierPolicy.reconcile(previous, rebuilt, false);
        assertTrue(projected.equalsDeep(result.getIdentifierFirstRep()));
        assertTrue(result.getIdentifier().get(1).getExtension().isEmpty());
        assertTrue(rebuilt.getIdentifierFirstRep().getExtension().isEmpty());
        rebuilt.getIdentifierFirstRep().addExtension(GoldenManualIdentifierPolicy.MANUAL, new BooleanType(true));
        assertThrows(InvalidRequestException.class,
                () -> GoldenManualIdentifierPolicy.reconcile(previous, rebuilt, true));
    }

    @Test
    void mergeLinkDeletionRequiresATransactionButOtherDeletesKeepTheirNativePath() {
        var calls = new int[1];
        var delegate = new ca.uhn.fhir.jpa.mdm.dao.MdmLinkDaoSvc<
                ca.uhn.fhir.jpa.model.dao.JpaPid, ca.uhn.fhir.jpa.entity.MdmLink>() {
            @Override
            public void deleteLink(ca.uhn.fhir.jpa.entity.MdmLink link) {
                calls[0]++;
            }
        };
        var service = new AtomicMergeMdmLinkDaoSvc(delegate);
        var link = new ca.uhn.fhir.jpa.entity.MdmLink();
        service.deleteLink(link);
        assertEquals(1, calls[0]);
        Patient from = new Patient();
        from.setId("Patient/from/_history/1");
        Patient to = new Patient();
        to.setId("Patient/to/_history/1");
        GoldenManualIdentifierPolicy.duringMerge(from, to, () -> {
            assertThrows(IllegalStateException.class, () -> service.deleteLink(link));
            assertEquals(1, calls[0]);
            return null;
        });
        service.deleteLink(link);
        assertEquals(2, calls[0]);
    }

    private Patient manual() {
        Patient result = new Patient();
        result.addIdentifier().setSystem("urn:manual").setValue("kept")
                .addExtension(GoldenManualIdentifierPolicy.MANUAL, new BooleanType(true));
        return result;
    }
}
