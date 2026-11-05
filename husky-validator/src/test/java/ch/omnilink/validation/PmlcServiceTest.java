package ch.omnilink.validation;

import static org.junit.jupiter.api.Assertions.*;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.zip.GZIPInputStream;
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

class PmlcServiceTest {
    private static PmlcService service;
    private static final ObjectMapper JSON = new ObjectMapper();
    @BeforeAll static void initialize() throws Exception { service = new PmlcService(); }

    @Test void profileContextUsesResourceLocationWithoutClaimingCausalAttribution() throws Exception {
        var bundle = JSON.readTree("""
                {"entry":[{"resource":{"meta":{"profile":["urn:synthetic:resource-profile"]}}}]}
                """);
        var outcome = (com.fasterxml.jackson.databind.node.ObjectNode) JSON.readTree("""
                {"resourceType":"OperationOutcome","issue":[
                  {"severity":"error","expression":["Bundle.entry[0].resource/*Immunization/synthetic*/.vaccineCode"]},
                  {"severity":"warning","location":["Bundle.entry[0].resource.code"]},
                  {"severity":"warning","expression":["Bundle.entry[0].resource.contained[0].code"]},
                  {"severity":"warning","expression":["Bundle.entry[99].resource.code"]},
                  {"severity":"warning","expression":["Bundle.entry[99999999999999999999].resource.code"]},
                  {"severity":"warning","expression":["Bundle"]}
                ]}
                """);
        String original = bundle.toString();
        OfflineFhirValidator.addProfileContext(outcome, bundle, "urn:synthetic:run-profile");
        assertEquals(original, bundle.toString());
        assertEquals("urn:synthetic:run-profile", outcome.path("extension").get(0).path("valueString").asText());
        for (int i = 0; i < 2; i++) {
            var extension = outcome.path("issue").get(i).path("extension").get(0);
            assertEquals("urn:omnilink:validation:context-profile", extension.path("url").asText());
            assertEquals("urn:synthetic:resource-profile", extension.path("valueString").asText());
        }
        for (int i = 2; i < 6; i++) assertFalse(outcome.path("issue").get(i).has("extension"));
    }

    private JsonNode input() throws Exception {
        return JSON.readTree("""
                {"language":"de-CH","confidentiality":"restricted",
                 "patientReference":"urn:uuid:00000000-0000-4000-8000-000000000001",
                 "source":{"resourceType":"Bundle","type":"collection","entry":[
                  {"fullUrl":"urn:uuid:00000000-0000-4000-8000-000000000001","resource":{
                    "resourceType":"Patient","id":"p1","name":[{"family":"Synthetic"}]}},
                  {"fullUrl":"urn:uuid:00000000-0000-4000-8000-000000000002","resource":{
                    "resourceType":"MedicationStatement","id":"s1","status":"active",
                    "subject":{"reference":"urn:uuid:00000000-0000-4000-8000-000000000001"},
                    "medicationCodeableConcept":{"text":"Synthetic medication"},
                    "dosage":[{"text":"Synthetic dosage"}]}}
                 ]}}
                """);
    }

    @Test void buildsDocumentAndValidatesMissingEprFieldsWithoutInventingThem() throws Exception {
        var input = input();
        String original = input.toString();
        var response = service.generate(input);
        assertEquals("invalid", response.path("status").asText());
        assertEquals(original, input.toString());
        var bundle = response.path("bundle");
        assertEquals("document", bundle.path("type").asText());
        boolean versioned = false;
        for (var profile : bundle.path("meta").path("profile")) {
            versioned |= PmlcService.DOCUMENT_PROFILE.equals(profile.asText());
        }
        assertTrue(versioned);
        var composition = bundle.path("entry").get(0).path("resource");
        assertEquals("Composition", composition.path("resourceType").asText());
        assertEquals(bundle.path("identifier"), composition.path("identifier"));
        assertEquals("Medikationsplan", composition.path("title").asText());
        assertEquals("de-CH", composition.path("language").asText());
        assertEquals("R", composition.path("confidentiality").asText());
        assertEquals("OperationOutcome", response.path("validation").path("resourceType").asText());
        boolean error = false;
        boolean missingRepresentation = false;
        for (var issue : response.path("validation").path("issue")) {
            error |= "error".equals(issue.path("severity").asText()) || "fatal".equals(issue.path("severity").asText());
            String diagnostics = issue.path("diagnostics").asText();
            missingRepresentation |= diagnostics.contains("originalRepresentation");
            assertFalse(diagnostics.contains("Unknown profile"), diagnostics);
            assertFalse(diagnostics.contains("bundle-composition-same-id"), diagnostics);
            assertFalse(diagnostics.contains("pmlc-composition-title"), diagnostics);
        }
        assertTrue(error);
        assertTrue(missingRepresentation, response.path("validation").toString());
        for (var entry : bundle.path("entry")) {
            var resource = entry.path("resource");
            if ("MedicationStatement".equals(resource.path("resourceType").asText())) {
                assertFalse(resource.has("dateAsserted"));
                assertFalse(resource.has("informationSource"));
                assertEquals("Synthetic dosage", resource.path("dosage").get(0).path("text").asText());
            }
        }
        assertFalse(response.path("coverage").path("clinicalReconciliation").asBoolean());
    }

    @Test void rejectsInactiveOrForeignStatementsBeforeGeneration() throws Exception {
        var input = input();
        ((com.fasterxml.jackson.databind.node.ObjectNode) input.path("source").path("entry").get(1).path("resource"))
                .put("status", "stopped");
        assertThrows(IllegalArgumentException.class, () -> service.generate(input));
        var foreign = input();
        ((com.fasterxml.jackson.databind.node.ObjectNode) foreign.path("source").path("entry").get(1)
                .path("resource").path("subject")).put("reference", "Patient/other");
        assertThrows(IllegalArgumentException.class, () -> service.generate(foreign));
    }

    @Test void localizedTitlesAndAddressDependencyMatchDeclaredProfiles() throws Exception {
        for (String[] language : new String[][]{
                {"fr-CH", "Plan de médication"}, {"it-CH", "Piano farmacologico"}}) {
            var input = (com.fasterxml.jackson.databind.node.ObjectNode) input();
            input.put("language", language[0]);
            var patient = (com.fasterxml.jackson.databind.node.ObjectNode)
                    input.path("source").path("entry").get(0).path("resource");
            patient.putArray("address").addObject()
                    .put("city", "Synthetic").put("postalCode", "0000").put("country", "CH")
                    .putObject("_country").putArray("extension").addObject()
                    .put("url", "http://hl7.org/fhir/StructureDefinition/iso21090-codedString")
                    .putObject("valueCoding").put("system", "urn:iso:std:iso:3166").put("code", "CH");
            var response = service.generate(input);
            assertEquals(language[1], response.path("bundle").path("entry").get(0)
                    .path("resource").path("title").asText());
            for (var issue : response.path("validation").path("issue")) {
                String diagnostics = issue.path("diagnostics").asText();
                assertFalse(diagnostics.contains("could not be resolved"), diagnostics);
                assertFalse(diagnostics.contains("bundle-composition-same-id"), diagnostics);
                assertFalse(diagnostics.contains("pmlc-composition-title"), diagnostics);
            }
        }
    }

    @Test void sourceConfidentialityCannotBeDowngradedEvenViaInternalService() throws Exception {
        var input = input();
        ((com.fasterxml.jackson.databind.node.ObjectNode) input.path("source").path("entry").get(0).path("resource"))
                .putObject("meta").putArray("security").addObject()
                .put("system", "http://terminology.hl7.org/CodeSystem/v3-Confidentiality").put("code", "V");
        assertThrows(IllegalArgumentException.class, () -> service.generate(input));
    }

    @Test void vacdValidationUsesStableProfilesAndDoesNotRepairInput() throws Exception {
        var bundle = JSON.readTree("""
                {"resourceType":"Bundle","type":"document","entry":[
                  {"fullUrl":"urn:uuid:00000000-0000-4000-8000-000000000003","resource":{
                    "resourceType":"Composition","status":"final",
                    "meta":{"profile":["http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-composition-immunization-administration|6.0.0"]},
                    "title":"Synthetic VACD"}}]}
                """);
        String original = bundle.toString();
        var outcome = service.validateVacd(bundle);
        assertEquals(original, bundle.toString());
        assertEquals("OperationOutcome", outcome.path("resourceType").asText());
        boolean errors = false;
        for (var issue : outcome.path("issue")) {
            errors |= java.util.List.of("error", "fatal").contains(issue.path("severity").asText());
            assertFalse(issue.path("diagnostics").asText().toLowerCase().contains("unknown profile"),
                    issue.toString());
        }
        assertTrue(errors, outcome.toString());
        assertTrue(outcome.toString().contains("CH-VACD 6.0.0"));
        assertFalse(outcome.toString().contains("7.0.0-ballot"));
    }

    @Test void vacdValidationRejectsWrongBundleTypeAndUnknownDeclaredProfiles() throws Exception {
        assertThrows(IllegalArgumentException.class, () -> service.validateVacd(null));
        assertThrows(IllegalArgumentException.class,
                () -> service.validateVacd(JSON.readTree("{\"resourceType\":\"Bundle\",\"type\":\"transaction\"}")));
        var bundle = JSON.readTree("""
                {"resourceType":"Bundle","type":"document",
                 "meta":{"profile":["http://example.invalid/StructureDefinition/unknown"]}}
                """);
        var outcome = service.validateVacd(bundle);
        boolean unknownError = false;
        for (var issue : outcome.path("issue")) {
            unknownError |= "error".equals(issue.path("severity").asText())
                    && issue.path("diagnostics").asText().contains("Declared profile unavailable");
        }
        assertTrue(unknownError, outcome.toString());
    }

    @Test void officialVacdSixExampleHasNoValidationErrors() throws Exception {
        try (var source = getClass().getResourceAsStream("/package/ch.fhir.ig.ch-vacd#6.0.0.tgz")) {
            assertNotNull(source);
            try (var archive = new TarArchiveInputStream(new GZIPInputStream(source))) {
                org.apache.commons.compress.archivers.tar.TarArchiveEntry entry;
                while ((entry = archive.getNextEntry()) != null) {
                    if ("package/example/Bundle-1-1-ImmunizationAdministration.json".equals(entry.getName())) {
                        var bundle = JSON.readTree(archive.readAllBytes());
                        String original = bundle.toString();
                        var outcome = service.validateVacd(bundle);
                        assertEquals(original, bundle.toString());
                        for (var issue : outcome.path("issue")) {
                            assertFalse(java.util.List.of("error", "fatal").contains(
                                    issue.path("severity").asText()), issue.toString());
                        }
                        return;
                    }

                }
                fail("Official synthetic VACD example missing from pinned package");
            }
        }
    }

    @Test void eprMedicationMappingChangesOnlyOutputAndRetainsSourceIdentifiersInProvenance() throws Exception {
        var source = (com.fasterxml.jackson.databind.node.ObjectNode) input();
        var statement = (com.fasterxml.jackson.databind.node.ObjectNode)
                source.path("source").path("entry").get(1).path("resource");
        statement.putArray("identifier").addObject()
                .put("system", "https://example.test/import").put("value", "stable-source-identifier");
        String original = source.toString();
        var response = service.generate(source);
        assertEquals(original, source.toString());
        var entries = response.path("bundle").path("entry");
        JsonNode outputStatement = null;
        JsonNode provenance = null;
        for (var entry : entries) {
            if ("MedicationStatement".equals(entry.path("resource").path("resourceType").asText())) {
                outputStatement = entry.get("resource");
            }
            if ("Provenance".equals(entry.path("resource").path("resourceType").asText())) {
                provenance = entry.get("resource");
            }
        }
        assertNotNull(outputStatement);
        assertNotNull(provenance);
        assertFalse(outputStatement.has("medicationCodeableConcept"));
        assertTrue(outputStatement.path("medicationReference").path("reference").asText().startsWith("#med-"));
        assertEquals("Synthetic medication", outputStatement.path("contained").get(0).path("code").path("text").asText());
        assertEquals("urn:ietf:rfc:3986", outputStatement.path("identifier").get(0).path("system").asText());
        assertTrue(outputStatement.path("identifier").get(0).path("value").asText().startsWith("urn:uuid:"));
        assertEquals(statement.get("identifier").get(0),
                provenance.path("entity").get(0).path("what").get("identifier"));
        var second = service.generate(source);
        for (var entry : second.path("bundle").path("entry")) {
            if ("MedicationStatement".equals(entry.path("resource").path("resourceType").asText())) {
                assertEquals(outputStatement.path("identifier"), entry.path("resource").path("identifier"));
            }
        }
        for (var issue : response.path("validation").path("issue")) {
            String diagnostics = issue.path("diagnostics").asText();
            assertFalse(diagnostics.contains("MedicationStatement.contained: minimum required"), diagnostics);
            assertFalse(diagnostics.contains("found type CodeableConcept"), diagnostics);
            assertFalse(diagnostics.contains("uuid-format"), diagnostics);
        }
    }

    @Test void referencedMedicationIsCopiedToContainedWithoutChangingSourceGraph() throws Exception {
        var source = (com.fasterxml.jackson.databind.node.ObjectNode) input();
        var statement = (com.fasterxml.jackson.databind.node.ObjectNode)
                source.path("source").path("entry").get(1).path("resource");
        statement.remove("medicationCodeableConcept");
        String medicationUrl = "urn:uuid:00000000-0000-4000-8000-000000000003";
        statement.putObject("medicationReference").put("reference", medicationUrl);
        ((com.fasterxml.jackson.databind.node.ArrayNode) source.path("source").path("entry"))
                .addObject().put("fullUrl", medicationUrl).putObject("resource")
                .put("resourceType", "Medication").put("id", "m1")
                .putObject("code").put("text", "Synthetic referenced drug");
        String original = source.toString();
        var response = service.generate(source);
        assertEquals(original, source.toString());
        for (var entry : response.path("bundle").path("entry")) {
            if ("MedicationStatement".equals(entry.path("resource").path("resourceType").asText())) {
                assertTrue(entry.path("resource").path("medicationReference").path("reference").asText().startsWith("#med-"));
                assertEquals("Synthetic referenced drug", entry.path("resource").path("contained").get(0)
                        .path("code").path("text").asText());
            }
        }
    }

    @Test void existingUuidAndSourceDoseArePreservedWhileKnownUnitsAreNormalized() throws Exception {
        var source = input().path("source");
        var statement = (com.fasterxml.jackson.databind.node.ObjectNode) source.path("entry").get(1)
                .path("resource").deepCopy();
        statement.putArray("identifier").addObject().put("system", "urn:ietf:rfc:3986")
                .put("value", "urn:uuid:00000000-0000-4000-8000-000000000009");
        var dosage = (com.fasterxml.jackson.databind.node.ObjectNode) statement.path("dosage").get(0);
        dosage.putArray("doseAndRate").addObject().putObject("doseQuantity").put("value", 1.25).put("unit", "mg");
        var identifiers = statement.path("identifier").deepCopy();
        PmlcMedicationMapper.map(statement, source, "urn:uuid:s", "urn:uuid:d", java.time.Instant.now());
        assertEquals(identifiers, statement.path("identifier"));
        var quantity = statement.path("dosage").get(0).path("doseAndRate").get(0).path("doseQuantity");
        assertEquals(1.25, quantity.path("value").asDouble());
        assertEquals("mg", quantity.path("code").asText());
        assertEquals("http://unitsofmeasure.org", quantity.path("system").asText());
    }

    @Test void actualPractitionerReferenceGetsRoleWithoutInventingOrganization() throws Exception {
        var source = (com.fasterxml.jackson.databind.node.ObjectNode) input().path("source");
        String practitionerUrl = "urn:uuid:00000000-0000-4000-8000-000000000004";
        source.withArray("entry").addObject().put("fullUrl", practitionerUrl)
                .putObject("resource").put("resourceType", "Practitioner").put("id", "pr1");
        var statement = (com.fasterxml.jackson.databind.node.ObjectNode)
                source.path("entry").get(1).path("resource").deepCopy();
        statement.putObject("informationSource").put("reference", practitionerUrl);
        var roles = JSON.createArrayNode();
        PmlcMedicationMapper.mapInformationSource(statement, source, roles);
        assertEquals(1, roles.size());
        assertEquals(roles.get(0).path("fullUrl"), statement.path("informationSource").path("reference"));
        assertEquals(practitionerUrl, roles.get(0).path("resource").path("practitioner").path("reference").asText());
        assertFalse(roles.get(0).path("resource").has("organization"));
        assertEquals("Practitioner", source.path("entry").get(2).path("resource").path("resourceType").asText());
    }
}
