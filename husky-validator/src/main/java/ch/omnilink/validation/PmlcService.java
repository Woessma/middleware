package ch.omnilink.validation;

import ca.uhn.fhir.parser.StrictErrorHandler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.HashSet;
import org.hl7.fhir.r4.model.Composition;
import org.hl7.fhir.r4.model.Narrative;
import org.hl7.fhir.r4.model.Reference;
import org.projecthusky.common.enums.LanguageCode;
import org.projecthusky.fhir.emed.ch.epr.resource.ChEmedEprDevice;
import org.projecthusky.fhir.emed.ch.epr.resource.pmlc.ChEmedEprCompositionPmlc;
import org.projecthusky.fhir.emed.ch.epr.resource.pmlc.ChEmedEprDocumentPmlc;

public final class PmlcService extends OfflineFhirValidator {
    public static final String BASE = "http://fhir.ch/ig/ch-emed-epr/StructureDefinition/";
    public static final String DOCUMENT_PROFILE = BASE + "ch-emed-epr-document-medicationcard|3.0.0";
    private final ObjectMapper json = new ObjectMapper();

    public PmlcService() throws IOException {
        super();
    }

    public synchronized ObjectNode generate(JsonNode input) throws IOException {
        if (input == null || !input.isObject()) {
            throw new IllegalArgumentException("PMLC request object required");
        }
        JsonNode source = input.path("source");
        if (!"Bundle".equals(source.path("resourceType").asText())
                || !"collection".equals(source.path("type").asText())
                || !source.path("entry").isArray()) {
            throw new IllegalArgumentException("Source collection Bundle required");
        }
        String patient = input.path("patientReference").asText();
        if (!patient.startsWith("urn:uuid:")) {
            throw new IllegalArgumentException("Local patient fullUrl required");
        }
        String language = input.path("language").asText();
        if (!List.of("de-CH", "fr-CH", "it-CH").contains(language)) {
            throw new IllegalArgumentException("Language must be de-CH, fr-CH or it-CH");
        }
        String confidentiality = input.path("confidentiality").asText();
        if (!List.of("normal", "restricted", "secret").contains(confidentiality)) {
            throw new IllegalArgumentException("Explicit document confidentiality required");
        }
        int patients = 0;
        int statements = 0;
        int requestedConfidentiality = switch (confidentiality) {
            case "normal" -> 0;
            case "restricted" -> 1;
            default -> 2;
        };
        var fullUrls = new HashSet<String>();
        for (JsonNode entry : source.path("entry")) {
            if (!entry.isObject() || !entry.path("resource").isObject()
                    || !entry.path("fullUrl").asText().startsWith("urn:uuid:")
                    || !fullUrls.add(entry.path("fullUrl").asText())) {
                throw new IllegalArgumentException("Unique local fullUrls and resources required");
            }
            JsonNode resource = entry.path("resource");
            String type = resource.path("resourceType").asText();
            if (!List.of("Patient", "MedicationStatement", "Medication", "PractitionerRole",
                    "Practitioner", "Organization", "RelatedPerson", "Device", "Encounter").contains(type)) {
                throw new IllegalArgumentException("Unsupported medication source resource");
            }
            for (var labels : resource.findValues("security")) {
                for (var security : labels) {
                    String system = security.path("system").asText();
                    String code = security.path("code").asText();
                    int sourceConfidentiality = -1;
                    if (List.of("http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                            "http://hl7.org/fhir/v3/Confidentiality").contains(system)) {
                        sourceConfidentiality = switch (code) { case "N" -> 0; case "R" -> 1; case "V" -> 2; default -> -1; };
                    } else if ("http://snomed.info/sct".equals(system)) {
                        sourceConfidentiality = switch (code) {
                            case "17621005" -> 0; case "263856008" -> 1; case "4554003" -> 2; default -> -1;
                        };
                    }
                    if (sourceConfidentiality > requestedConfidentiality) {
                        throw new IllegalArgumentException("Document confidentiality would downgrade source");
                    }
                }
            }
            if ("Patient".equals(type)) {
                patients++;
                if (!patient.equals(entry.path("fullUrl").asText())) {
                    throw new IllegalArgumentException("Patient reference does not match source");
                }
            }
            if ("MedicationRequest".equals(type)) {
                throw new IllegalArgumentException("MedicationRequests are not part of this output");
            }
            if ("MedicationStatement".equals(type)) {
                statements++;
                if (!"active".equals(resource.path("status").asText())
                        || !patient.equals(resource.path("subject").path("reference").asText())) {
                    throw new IllegalArgumentException("Only active statements for this patient are allowed");
                }
            }
        }
        if (patients != 1 || statements == 0) {
            throw new IllegalArgumentException("Exactly one patient and active statements required");
        }
        Instant now = Instant.now();
        var document = new ChEmedEprDocumentPmlc(UUID.randomUUID(), now);
        var composition = new ChEmedEprCompositionPmlc(UUID.randomUUID(), now, LanguageCode.GERMAN);
        composition.setIdentifier(document.getIdentifier().copy());
        composition.setLanguage(language);
        composition.setTitle(switch (language) {
            case "fr-CH" -> "Plan de médication";
            case "it-CH" -> "Piano farmacologico";
            default -> "Medikationsplan";
        });
        String confidentialityCode = switch (confidentiality) {
            case "normal" -> "17621005";
            case "secret" -> "4554003";
            default -> "263856008";
        };
        composition.setConfidentiality(switch (confidentiality) {
            case "normal" -> Composition.DocumentConfidentiality.N;
            case "secret" -> Composition.DocumentConfidentiality.V;
            default -> Composition.DocumentConfidentiality.R;
        });
        composition.getConfidentialityElement().getExtensionFirstRep().setValue(
                new org.hl7.fhir.r4.model.CodeableConcept().addCoding(
                        new org.hl7.fhir.r4.model.Coding("http://snomed.info/sct", confidentialityCode, null)));
        composition.setSubject(new Reference(patient));
        var device = new ChEmedEprDevice();
        device.setId(UUID.randomUUID().toString());
        device.addDeviceName().setName("OmniLink Middleware").setType(
                org.hl7.fhir.r4.model.Device.DeviceNameType.USERFRIENDLYNAME);
        device.addVersion().setValue("Husky 3.5.0");
        String deviceUrl = "urn:uuid:" + device.getId();
        composition.addAuthor(new Reference(deviceUrl));
        var section = composition.getCardSection();
        var narrative = new Narrative().setStatus(Narrative.NarrativeStatus.GENERATED);
        narrative.setDivAsString(narrative(source));
        section.setText(narrative);
        document.setComposition(composition);
        var parser = context.newJsonParser().setParserErrorHandler(new StrictErrorHandler());
        ObjectNode bundle = (ObjectNode) json.readTree(parser.encodeResourceToString(document));
        setProfile(bundle, DOCUMENT_PROFILE);
        var entries = bundle.withArray("entry");
        ObjectNode compositionJson = (ObjectNode) entries.get(0).get("resource");
        setProfile(compositionJson, BASE + "ch-emed-epr-composition-medicationcard|3.0.0");
        var securityLabels = json.createArrayNode();
        for (var entry : source.path("entry")) {
            for (var labels : entry.path("resource").findValues("security")) {
                for (var security : labels) {
                    if (!containsSecurity(securityLabels, security)) {
                        securityLabels.add(security.deepCopy());
                    }
                }
            }
        }
        if (!securityLabels.isEmpty()) {
            ((ObjectNode) bundle.get("meta")).set("security", securityLabels);
            ((ObjectNode) compositionJson.get("meta")).set("security", securityLabels.deepCopy());
        }
        var sectionEntries = ((ObjectNode) compositionJson.withArray("section").get(0)).putArray("entry");
        var provenanceEntries = json.createArrayNode();
        var authorRoleEntries = json.createArrayNode();
        for (JsonNode entry : source.path("entry")) {
            ObjectNode copy = entry.deepCopy();
            ObjectNode resource = (ObjectNode) copy.get("resource");
            String profile = switch (resource.path("resourceType").asText()) {
                case "Patient" -> "ch-emed-epr-patient";
                case "MedicationStatement" -> "ch-emed-epr-medicationstatement-card";
                case "Medication" -> "ch-emed-epr-medication";
                case "PractitionerRole" -> "ch-emed-epr-practitionerrole";
                case "RelatedPerson" -> "ch-emed-epr-related-person";
                default -> null;
            };
            if (profile != null) setProfile(resource, BASE + profile + "|3.0.0");
            if ("MedicationStatement".equals(resource.path("resourceType").asText())) {
                sectionEntries.addObject().put("reference", copy.path("fullUrl").asText());
                var provenance = PmlcMedicationMapper.map(
                        resource, source, copy.path("fullUrl").asText(), deviceUrl, now);
                PmlcMedicationMapper.mapInformationSource(resource, source, authorRoleEntries);
                if (provenance != null) {
                    provenanceEntries.addObject().put("fullUrl", "urn:uuid:" + provenance.path("id").asText())
                            .set("resource", provenance);
                }
            }
            entries.add(copy);
        }
        ObjectNode deviceJson = (ObjectNode) json.readTree(parser.encodeResourceToString(device));
        setProfile(deviceJson, BASE + "ch-emed-epr-device|3.0.0");
        entries.addObject().put("fullUrl", deviceUrl).set("resource", deviceJson);
        entries.addAll(provenanceEntries);
        entries.addAll(authorRoleEntries);

        var outcome = validateFinalJson(bundle, DOCUMENT_PROFILE);
        boolean hasErrors = false;
        for (var issue : outcome.path("issue")) {
            hasErrors |= List.of("error", "fatal").contains(issue.path("severity").asText());
        }
        ObjectNode response = json.createObjectNode();
        response.put("status", hasErrors ? "invalid" : "validated");
        response.set("bundle", bundle);
        response.set("validation", outcome);
        response.putObject("coverage").put("profile", DOCUMENT_PROFILE)
                .put("huskyVersion", "3.5.0").put("chEmedVersion", "6.0.0")
                .put("chCoreVersion", "6.0.0").put("terminology", "local-packages")
                .put("clinicalReconciliation", false).put("logicValidation", false)
                .put("originalRepresentationIncluded", false);
        return response;
    }

    private static void setProfile(ObjectNode resource, String profile) {
        ObjectNode meta = resource.has("meta") ? (ObjectNode) resource.get("meta") : resource.putObject("meta");
        var profiles = meta.withArray("profile");
        boolean exists = false;
        for (JsonNode existing : profiles) exists |= profile.equals(existing.asText());
        if (!exists) profiles.add(profile);
    }

    private static boolean containsSecurity(JsonNode labels, JsonNode label) {
        for (var existing : labels) if (existing.equals(label)) return true;
        return false;
    }

    private static String narrative(JsonNode source) {
        var html = new StringBuilder("<div xmlns=\"http://www.w3.org/1999/xhtml\"><p>"
                + "MedicationStatements with status active; not a clinical reconciliation."
                + "</p><table><thead><tr><th>Medication</th><th>Dosage from source</th></tr></thead><tbody>");
        for (var entry : source.path("entry")) {
            var statement = entry.path("resource");
            if (!"MedicationStatement".equals(statement.path("resourceType").asText())) continue;
            JsonNode coding = statement.path("medicationCodeableConcept");
            String reference = statement.path("medicationReference").path("reference").asText();
            if (!reference.isEmpty()) {
                if (reference.startsWith("#")) {
                    for (var contained : statement.path("contained")) {
                        if (reference.substring(1).equals(contained.path("id").asText())) coding = contained.path("code");
                    }
                } else {
                    for (var resource : source.path("entry")) {
                        if (reference.equals(resource.path("fullUrl").asText())) coding = resource.path("resource").path("code");
                    }
                }
            }
            String name = coding.path("text").asText();
            if (name.isEmpty()) {
                var labels = new java.util.ArrayList<String>();
                for (var code : coding.path("coding")) {
                    String display = code.path("display").asText();
                    labels.add(display.isEmpty()
                            ? code.path("system").asText() + " / " + code.path("code").asText() : display);
                }
                name = labels.isEmpty() ? reference : String.join("; ", labels);
            }
            html.append("<tr><td>").append(escape(name)).append("</td><td>");
            for (var dosage : statement.path("dosage")) {
                html.append("<p>").append(escape(dosage.toString())).append("</p>");
            }
            html.append("</td></tr>");
        }
        return html.append("</tbody></table></div>").toString();
    }

    private static String escape(String value) {
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }
}
