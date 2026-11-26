package ch.omnilink.fhir.mdm.extension;

import ca.uhn.fhir.rest.server.exceptions.InvalidRequestException;
import ca.uhn.fhir.mdm.util.MdmResourceUtil;
import ca.uhn.fhir.mdm.api.MdmConstants;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;
import org.hl7.fhir.r4.model.BooleanType;
import org.hl7.fhir.r4.model.Identifier;
import org.hl7.fhir.r4.model.Patient;

public final class GoldenManualIdentifierPolicy {
    public static final String MANUAL = "urn:omnilink:mdm:identifier-projection:manual";
    public static final String MANUAL_EDIT_CONTEXT = GoldenManualIdentifierPolicy.class.getName() + ".manual-edit";
    private static final ThreadLocal<Merge> ACTIVE_MERGE = new ThreadLocal<>();
    private record Key(String system, String value) {}
    private record Merge(Patient from, Patient to, Patient baseline) {}

    static <T> T duringMerge(Patient storedFrom, Patient storedTo, Supplier<T> action) {
        if (ACTIVE_MERGE.get() != null) {
            throw new InvalidRequestException("Nested Golden merge identifier context");
        }
        if (samePatient(storedFrom, storedTo)) {
            throw new InvalidRequestException("Cannot merge a Golden Patient into itself");
        }
        Patient baseline = storedTo.copy();
        Map<Key, Identifier> destination = index(baseline);
        Map<Key, Identifier> source = index(storedFrom);
        for (var entry : source.entrySet()) {
            Identifier existing = destination.get(entry.getKey());
            if (existing != null && (manual(existing) || manual(entry.getValue()))
                    && !existing.equalsDeep(entry.getValue())) {
                throw new InvalidRequestException("Conflicting Golden manual identifier ownership or metadata");
            }
            if (manual(entry.getValue()) && existing == null) {
                baseline.addIdentifier(entry.getValue().copy());
            }
        }
        var combined = new ArrayList<>(storedTo.getIdentifier());
        combined.addAll(storedFrom.getIdentifier());
        GoldenIdentifierReconciler.normalizeMergedIdentifiers(combined);
        // Native meta-delete reconstructs resources; scope authorization to this synchronous merge, not object identity.
        var context = new Merge(storedFrom.copy(), storedTo.copy(), baseline);
        try {
            ACTIVE_MERGE.set(context);
            return action.get();
        } finally {
            ACTIVE_MERGE.remove();
        }
    }

    static boolean mergeActive() {
        return ACTIVE_MERGE.get() != null;
    }

    static boolean reconcileMerge(Patient previous, Patient incoming) {
        Merge merge = ACTIVE_MERGE.get();
        if (merge == null || (!samePatient(incoming, merge.from()) && !samePatient(incoming, merge.to()))) {
            return false;
        }
        Patient baseline;
        if (samePatient(incoming, merge.to()) && sameVersion(previous, merge.to())
                && MdmResourceUtil.isGoldenRecord(incoming)
                && !MdmResourceUtil.isGoldenRecordRedirected(incoming)) {
            baseline = merge.baseline();
        } else if (samePatient(incoming, merge.from()) && sameVersion(previous, merge.from())
                && MdmResourceUtil.isGoldenRecordRedirected(incoming)) {
            baseline = merge.from();
        } else if (samePatient(incoming, merge.from()) && sameVersion(previous, merge.from())
                && MdmResourceUtil.isGoldenRecord(previous) && !MdmResourceUtil.isGoldenRecord(incoming)) {
            Patient expected = previous.copy();
            expected.getMeta().getTag().removeIf(tag ->
                    MdmConstants.SYSTEM_GOLDEN_RECORD_STATUS.equals(tag.getSystem())
                            && MdmConstants.CODE_GOLDEN_RECORD.equals(tag.getCode()));
            if (!expected.equalsDeep(incoming)) {
                throw new InvalidRequestException("Golden merge tag removal cannot change Patient content");
            }
            return true;
        } else {
            throw new InvalidRequestException("Golden merge identifier context does not match stored snapshots");
        }
        Patient normalized = incoming.copy();
        normalized.setIdentifier(GoldenIdentifierReconciler.normalizeMergedIdentifiers(incoming.getIdentifier()));
        incoming.setIdentifier(reconcile(baseline, normalized, false).getIdentifier());
        return true;
    }

    private static boolean samePatient(Patient first, Patient second) {
        return first.getIdElement().hasIdPart()
                && first.getIdElement().getIdPart().equals(second.getIdElement().getIdPart());
    }

    private static boolean sameVersion(Patient first, Patient second) {
        return samePatient(first, second) && first.getIdElement().hasVersionIdPart()
                && first.getIdElement().getVersionIdPart().equals(second.getIdElement().getVersionIdPart());
    }

    public static Patient reconcile(Patient previous, Patient incoming, boolean manualRequest) {
        Map<Key, Identifier> old = index(previous);
        Patient result = incoming.copy();
        Map<Key, Identifier> current = index(result);
        for (var entry : current.entrySet()) {
            Identifier original = old.get(entry.getKey());
            if (original != null && projected(original)) {
                if (manual(entry.getValue())) {
                    throw new InvalidRequestException("Projected identifiers cannot become manual Golden ownership");
                }
                GoldenIdentifierReconciler.preserveManagedOwnership(original, entry.getValue());
            }
        }
        if (manualRequest) {
            for (Identifier identifier : result.getIdentifier()) {
                if (!usable(identifier) && previous.getIdentifier().stream().noneMatch(identifier::equalsDeep)) {
                    throw new InvalidRequestException("Manual Golden identifier requires system and value");
                }
            }
            for (var entry : current.entrySet()) {
                Identifier identifier = entry.getValue();
                Identifier original = old.get(entry.getKey());
                if (!projected(identifier) && (manual(identifier) || original == null
                        || manual(original))) {
                    identifier.getExtension().removeIf(e -> MANUAL.equals(e.getUrl()));
                    identifier.addExtension(MANUAL, new BooleanType(true));
                }
            }
        } else {
            for (var entry : current.entrySet()) {
                Identifier original = old.get(entry.getKey());
                if (manual(entry.getValue()) && (original == null || !manual(original))) {
                    throw new InvalidRequestException("Internal writes cannot create manual Golden ownership");
                }
            }
            for (var entry : old.entrySet()) {
                if (!manual(entry.getValue())) {
                    continue;
                }
                Identifier replacement = current.get(entry.getKey());
                if (replacement == null) {
                    result.addIdentifier(entry.getValue().copy());
                } else {
                    result.getIdentifier().set(result.getIdentifier().indexOf(replacement), entry.getValue().copy());
                }
            }
        }
        return result;
    }

    private static Map<Key, Identifier> index(Patient patient) {
        Map<Key, Identifier> result = new LinkedHashMap<>();
        for (Identifier identifier : patient.getIdentifier()) {
            boolean marked = manual(identifier);
            if (marked && (!usable(identifier) || projected(identifier))) {
                throw new InvalidRequestException("Invalid manual Golden identifier ownership");
            }
            if (identifier.hasSystem() && identifier.hasValue()
                    && result.putIfAbsent(new Key(identifier.getSystem(), identifier.getValue()), identifier) != null) {
                throw new InvalidRequestException("Duplicate Golden identifier");
            }
        }
        return result;
    }

    private static boolean usable(Identifier identifier) {
        return identifier.hasSystem() && !identifier.getSystem().isBlank()
                && identifier.hasValue() && !identifier.getValue().isBlank();
    }

    private static boolean manual(Identifier identifier) {
        var markers = identifier.getExtensionsByUrl(MANUAL);
        if (markers.isEmpty()) {
            return false;
        }
        if (markers.size() != 1 || markers.get(0).hasExtension()
                || !(markers.get(0).getValue() instanceof BooleanType value) || !value.booleanValue()) {
            throw new InvalidRequestException("Invalid manual Golden identifier marker");
        }
        return true;
    }

    private static boolean projected(Identifier identifier) {
        return !identifier.getExtensionsByUrl(GoldenIdentifierReconciler.MANAGED).isEmpty()
                || !identifier.getExtensionsByUrl(GoldenIdentifierReconciler.SOURCE).isEmpty();
    }

    private GoldenManualIdentifierPolicy() {}
}
