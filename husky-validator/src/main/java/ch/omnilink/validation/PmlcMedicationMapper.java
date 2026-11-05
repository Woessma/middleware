package ch.omnilink.validation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;

final class PmlcMedicationMapper {
    private static final ObjectMapper JSON = new ObjectMapper();

    static ObjectNode map(ObjectNode statement, JsonNode source, String fullUrl, String deviceUrl, Instant now) {
        JsonNode originalIdentifiers = statement.path("identifier").deepCopy();
        String identity = statement.path("id").asText() + "|" + originalIdentifiers;
        UUID uuid = UUID.nameUUIDFromBytes(identity.getBytes(StandardCharsets.UTF_8));
        boolean alreadyUuid = false;
        if (originalIdentifiers.isArray() && originalIdentifiers.size() == 1) {
            var identifier = originalIdentifiers.get(0);
            alreadyUuid = "urn:ietf:rfc:3986".equals(identifier.path("system").asText())
                    && identifier.path("value").asText().matches(
                            "urn:uuid:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}");
        }
        if (!alreadyUuid) {
            statement.putArray("identifier").addObject()
                    .put("system", "urn:ietf:rfc:3986").put("value", "urn:uuid:" + uuid);
        }
        for (var dosage : statement.path("dosage")) {
            for (var doseAndRate : dosage.path("doseAndRate")) {
                var quantity = doseAndRate.path("doseQuantity");
                if (!quantity.isObject() || quantity.has("system")) continue;
                String unit = quantity.path("code").asText(quantity.path("unit").asText());
                if (java.util.Set.of("mg", "g", "kg", "ug", "ng", "mL", "L", "mmol", "mol", "[iU]", "1")
                        .contains(unit)) {
                    ((ObjectNode) quantity).put("system", "http://unitsofmeasure.org").put("code", unit);
                }
            }
        }
        JsonNode medication = null;
        if (statement.has("medicationCodeableConcept")) {
            var contained = JSON.createObjectNode().put("resourceType", "Medication");
            contained.set("code", statement.get("medicationCodeableConcept").deepCopy());
            medication = contained;
        } else {
            String reference = statement.path("medicationReference").path("reference").asText();
            if (reference.startsWith("#")) {
                for (var item : statement.path("contained")) {
                    if (reference.substring(1).equals(item.path("id").asText())
                            && "Medication".equals(item.path("resourceType").asText())) {
                        medication = item;
                    }
                }
            } else {
                for (var entry : source.path("entry")) {
                    if (reference.equals(entry.path("fullUrl").asText())
                            && "Medication".equals(entry.path("resource").path("resourceType").asText())) {
                        medication = entry.get("resource");
                    }
                }
            }
        }
        if (medication != null) {
            String reference = statement.path("medicationReference").path("reference").asText();
            if (reference.startsWith("#") && !statement.has("medicationCodeableConcept")) {
                setMedicationProfile((ObjectNode) medication);
            } else {
                var contained = (ObjectNode) medication.deepCopy();
                String id = "med-" + uuid;
                for (var item : statement.path("contained")) {
                    if (id.equals(item.path("id").asText())) {
                        throw new IllegalArgumentException("Contained medication ID collision");
                    }
                }
                contained.put("id", id);
                if (contained.path("meta").isObject()) {
                    var meta = (ObjectNode) contained.path("meta");
                    meta.remove(java.util.List.of("versionId", "lastUpdated", "security"));
                }
                setMedicationProfile(contained);
                statement.withArray("contained").add(contained);
                statement.putObject("medicationReference").put("reference", "#" + id);
            }
            statement.remove("medicationCodeableConcept");
        }
        if (!originalIdentifiers.isArray() || originalIdentifiers.isEmpty()) return null;
        var provenance = JSON.createObjectNode().put("resourceType", "Provenance");
        provenance.put("id", UUID.randomUUID().toString()).put("recorded", now.toString());
        provenance.putArray("target").addObject().put("reference", fullUrl);
        var agent = provenance.putArray("agent").addObject();
        agent.putObject("who").put("reference", deviceUrl);
        for (var identifier : originalIdentifiers) {
            var entity = provenance.withArray("entity").addObject().put("role", "source");
            entity.putObject("what").set("identifier", identifier.deepCopy());
        }
        return provenance;
    }

    static void mapInformationSource(ObjectNode statement, JsonNode source,
                                     com.fasterxml.jackson.databind.node.ArrayNode roles) {
        String reference = statement.path("informationSource").path("reference").asText();
        if (reference.isEmpty()) return;
        for (var entry : source.path("entry")) {
            var practitioner = entry.path("resource");
            if (!reference.equals(entry.path("fullUrl").asText())
                    || !"Practitioner".equals(practitioner.path("resourceType").asText())) continue;
            String id = UUID.nameUUIDFromBytes(("PMLC-author-role|" + practitioner.path("id")
                    + "|" + practitioner.path("identifier")).getBytes(StandardCharsets.UTF_8)).toString();
            String roleUrl = "urn:uuid:" + id;
            boolean present = false;
            for (var role : roles) present |= roleUrl.equals(role.path("fullUrl").asText());
            if (!present) {
                var role = roles.addObject().put("fullUrl", roleUrl).putObject("resource");
                role.put("resourceType", "PractitionerRole").put("id", id);
                role.putObject("meta").putArray("profile")
                        .add(PmlcService.BASE + "ch-emed-epr-practitionerrole|3.0.0");
                role.putObject("practitioner").put("reference", reference);
            }
            ((ObjectNode) statement.get("informationSource")).put("reference", roleUrl);
            return;
        }
    }

    private static void setMedicationProfile(ObjectNode medication) {
        var meta = medication.path("meta").isObject()
                ? (ObjectNode) medication.get("meta") : medication.putObject("meta");
        String profile = PmlcService.BASE + "ch-emed-epr-medication|3.0.0";
        var profiles = meta.withArray("profile");
        for (var item : profiles) if (profile.equals(item.asText())) return;
        profiles.add(profile);
    }
}
