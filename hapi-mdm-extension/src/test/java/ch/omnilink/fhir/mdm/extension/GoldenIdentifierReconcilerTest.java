package ch.omnilink.fhir.mdm.extension;

import static org.junit.jupiter.api.Assertions.*;

import java.util.List;
import org.hl7.fhir.r4.model.BooleanType;
import org.hl7.fhir.r4.model.Patient;
import org.hl7.fhir.r4.model.Reference;
import org.junit.jupiter.api.Test;

class GoldenIdentifierReconcilerTest {
    @Test
    void tracksSharedOwnershipReplacesChangedIdsAndRemovesOnlyManagedIdentifiers() {
        Patient golden = source("golden", "urn:native", "preserved");
        Patient first = source("first", "urn:source", "shared");
        first.addIdentifier().setSystem("urn:other").setValue("old");
        Patient second = source("second", "urn:source", "shared");
        Patient both = GoldenIdentifierReconciler.reconcile(golden, List.of(first, second));
        assertEquals(1, golden.getIdentifier().size());
        var shared = both.getIdentifier().stream().filter(i -> "shared".equals(i.getValue())).findFirst().orElseThrow();
        assertEquals(List.of("Patient/first", "Patient/second"),
                shared.getExtensionsByUrl(GoldenIdentifierReconciler.SOURCE).stream()
                        .map(e -> ((Reference) e.getValue()).getReference()).toList());
        assertTrue(both.equalsDeep(GoldenIdentifierReconciler.reconcile(both, List.of(second, first))));
        first.getIdentifier().get(1).setValue("new");
        Patient changed = GoldenIdentifierReconciler.reconcile(both, List.of(first));
        assertFalse(changed.getIdentifier().stream().anyMatch(i -> "old".equals(i.getValue())));
        assertTrue(changed.getIdentifier().stream().anyMatch(i -> "new".equals(i.getValue())));
        Patient none = GoldenIdentifierReconciler.reconcile(changed, List.of());
        assertTrue(golden.equalsDeep(none));
    }

    @Test
    void doesNotAdoptOrRemoveAnUnmanagedNativeIdentifier() {
        Patient golden = source("golden", "urn:source", "same");
        Patient source = source("source", "urn:source", "same");
        Patient projected = GoldenIdentifierReconciler.reconcile(golden, List.of(source));
        assertTrue(golden.equalsDeep(GoldenIdentifierReconciler.reconcile(projected, List.of())));
    }

    @Test
    void rejectsMalformedProvenanceAndAmbiguousIdentifiersWithoutMutatingTheGolden() {
        Patient bad = source("golden", "urn:source", "value");
        bad.getIdentifierFirstRep().addExtension(GoldenIdentifierReconciler.MANAGED, new BooleanType(true));
        Patient original = bad.copy();
        assertThrows(IllegalArgumentException.class, () -> GoldenIdentifierReconciler.reconcile(bad, List.of()));
        assertTrue(original.equalsDeep(bad));
        Patient duplicate = source("golden", "urn:source", "value");
        duplicate.addIdentifier().setSystem("urn:source").setValue("value");
        assertThrows(IllegalArgumentException.class,
                () -> GoldenIdentifierReconciler.reconcile(duplicate, List.of()));
        assertThrows(IllegalArgumentException.class,
                () -> GoldenIdentifierReconciler.reconcile(new Patient(), List.of(new Patient())));
        Patient valid = source("source", "urn:source", "value");
        assertThrows(IllegalArgumentException.class,
                () -> GoldenIdentifierReconciler.reconcile(new Patient(), List.of(valid, valid)));
    }

    private static Patient source(String id, String system, String value) {
        Patient result = new Patient();
        result.setId(id);
        result.addIdentifier().setSystem(system).setValue(value);
        return result;
    }
}
