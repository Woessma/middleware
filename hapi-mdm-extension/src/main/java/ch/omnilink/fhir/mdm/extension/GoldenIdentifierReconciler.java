package ch.omnilink.fhir.mdm.extension;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.TreeSet;
import org.hl7.fhir.r4.model.BooleanType;
import org.hl7.fhir.r4.model.Extension;
import org.hl7.fhir.r4.model.Identifier;
import org.hl7.fhir.r4.model.Patient;
import org.hl7.fhir.r4.model.Reference;

public final class GoldenIdentifierReconciler {
    public static final String MANAGED = "urn:omnilink:mdm:identifier-projection:managed";
    public static final String SOURCE = "urn:omnilink:mdm:identifier-projection:source";
    private record Key(String system, String value) {}

    static List<Identifier> normalizeMergedIdentifiers(List<Identifier> identifiers) {
        Map<Key, Identifier> merged = new HashMap<>();
        List<Identifier> result = new ArrayList<>();
        for (Identifier identifier : identifiers) {
            boolean managed = isManaged(identifier);
            if (managed) {
                validateOwners(identifier);
            }
            if (!identifier.hasSystem() || !identifier.hasValue()) {
                if (managed) {
                    throw new IllegalArgumentException("Managed identifier requires system and value");
                }
                result.add(identifier.copy());
                continue;
            }
            Key key = new Key(identifier.getSystem(), identifier.getValue());
            Identifier copy = identifier.copy();
            Identifier existing = merged.putIfAbsent(key, copy);
            if (existing == null) {
                result.add(copy);
                continue;
            }
            if (existing.equalsDeep(identifier)) {
                continue;
            }
            if (!managed || !isManaged(existing)) {
                throw new IllegalArgumentException("Conflicting merged Golden identifiers");
            }
            Identifier first = existing.copy();
            Identifier second = identifier.copy();
            first.getExtension().removeIf(e -> SOURCE.equals(e.getUrl()));
            second.getExtension().removeIf(e -> SOURCE.equals(e.getUrl()));
            if (!first.equalsDeep(second)) {
                throw new IllegalArgumentException("Conflicting merged managed identifier metadata");
            }
            Set<String> owners = new TreeSet<>();
            for (Identifier contribution : List.of(existing, identifier)) {
                for (Extension owner : contribution.getExtensionsByUrl(SOURCE)) {
                    owners.add(((Reference) owner.getValue()).getReference());
                }
            }
            setOwners(existing, owners);
        }
        return result;
    }

    static void preserveManagedOwnership(Identifier previous, Identifier incoming) {
        if (!isManaged(previous)) {
            return;
        }
        validateOwners(previous);
        if (isManaged(incoming)) {
            validateOwners(incoming);
            return;
        }
        for (Extension extension : previous.getExtension()) {
            if (MANAGED.equals(extension.getUrl()) || SOURCE.equals(extension.getUrl())) {
                incoming.addExtension(extension.copy());
            }
        }
    }

    public static Patient reconcile(Patient golden, List<Patient> confirmedSources) {
        Map<Key, Set<String>> projected = new TreeMap<>(
                Comparator.comparing(Key::system).thenComparing(Key::value));
        Set<String> seenSources = new HashSet<>();
        for (Patient source : confirmedSources) {
            if (!source.getIdElement().hasIdPart()) {
                throw new IllegalArgumentException("Confirmed Patient source requires an id");
            }
            String reference = "Patient/" + source.getIdElement().getIdPart();
            if (!validReference(reference) || !seenSources.add(reference)) {
                throw new IllegalArgumentException("Invalid or duplicate confirmed Patient source");
            }
            for (Identifier identifier : source.getIdentifier()) {
                if (!identifier.hasSystem() || identifier.getSystem().isBlank()
                        || !identifier.hasValue() || identifier.getValue().isBlank()) {
                    throw new IllegalArgumentException("Source identifier requires system and value");
                }
                projected.computeIfAbsent(new Key(identifier.getSystem(), identifier.getValue()),
                        ignored -> new TreeSet<>()).add(reference);
            }
        }

        Patient result = golden.copy();
        Map<Key, Identifier> existing = new HashMap<>();
        List<Identifier> retained = new ArrayList<>();
        for (Identifier identifier : result.getIdentifier()) {
            boolean managed = isManaged(identifier);
            if (!identifier.hasSystem() || !identifier.hasValue()) {
                if (managed) {
                    throw new IllegalArgumentException("Managed identifier requires system and value");
                }
                retained.add(identifier);
                continue;
            }
            Key key = new Key(identifier.getSystem(), identifier.getValue());
            if (existing.putIfAbsent(key, identifier) != null) {
                throw new IllegalArgumentException("Duplicate Golden Patient identifier");
            }
            if (managed) {
                validateOwners(identifier);
                Set<String> owners = projected.remove(key);
                if (owners != null) {
                    setOwners(identifier, owners);
                    retained.add(identifier);
                }
            } else {
                projected.remove(key);
                retained.add(identifier);
            }
        }
        for (var entry : projected.entrySet()) {
            Identifier identifier = new Identifier()
                    .setSystem(entry.getKey().system()).setValue(entry.getKey().value());
            identifier.addExtension(new Extension(MANAGED, new BooleanType(true)));
            setOwners(identifier, entry.getValue());
            retained.add(identifier);
        }
        result.setIdentifier(retained);
        return result;
    }

    private static boolean isManaged(Identifier identifier) {
        List<Extension> markers = identifier.getExtensionsByUrl(MANAGED);
        if (markers.isEmpty()) {
            if (!identifier.getExtensionsByUrl(SOURCE).isEmpty()) {
                throw new IllegalArgumentException("Identifier provenance without managed marker");
            }
            return false;
        }
        if (markers.size() != 1 || markers.get(0).hasExtension()
                || !(markers.get(0).getValue() instanceof BooleanType value) || !value.booleanValue()) {
            throw new IllegalArgumentException("Invalid managed identifier marker");
        }
        return true;
    }

    private static void validateOwners(Identifier identifier) {
        Set<String> seen = new HashSet<>();
        List<Extension> owners = identifier.getExtensionsByUrl(SOURCE);
        if (owners.isEmpty()) {
            throw new IllegalArgumentException("Managed identifier has no source");
        }
        for (Extension owner : owners) {
            if (owner.hasExtension() || !(owner.getValue() instanceof Reference reference)
                    || !validReference(reference.getReference()) || !seen.add(reference.getReference())) {
                throw new IllegalArgumentException("Invalid identifier provenance");
            }
        }
    }

    private static void setOwners(Identifier identifier, Set<String> owners) {
        identifier.getExtension().removeIf(extension -> SOURCE.equals(extension.getUrl()));
        for (String owner : owners) {
            identifier.addExtension(new Extension(SOURCE, new Reference(owner)));
        }
    }

    private static boolean validReference(String reference) {
        return reference != null && reference.matches("Patient/[A-Za-z0-9.-]{1,64}");
    }

    private GoldenIdentifierReconciler() {}
}
