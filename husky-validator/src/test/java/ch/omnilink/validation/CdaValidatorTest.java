package ch.omnilink.validation;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.projecthusky.validation.service.schematron.SchematronTransformer;

class CdaValidatorTest {
    @TempDir Path definitions;
    private static final byte[] VALID_XML = """
            <ClinicalDocument xmlns="urn:hl7-org:v3">
              <typeId root="2.16.840.1.113883.1.3" extension="POCD_HD000040"/>
              <templateId root="2.16.840.1.113883.10.20.22.1.1"/>
              <id root="1.2.3"/>
              <code code="34133-9" codeSystem="2.16.840.1.113883.6.1"/>
              <title>Synthetic document</title>
              <effectiveTime value="20261105"/>
              <confidentialityCode code="N" codeSystem="2.16.840.1.113883.5.25"/>
              <recordTarget><patientRole><id nullFlavor="UNK"/></patientRole></recordTarget>
              <author><time nullFlavor="UNK"/><assignedAuthor><id nullFlavor="UNK"/></assignedAuthor></author>
              <custodian><assignedCustodian><representedCustodianOrganization>
                <id nullFlavor="UNK"/>
              </representedCustodianOrganization></assignedCustodian></custodian>
              <component><nonXMLBody><text mediaType="text/plain">Synthetic</text></nonXMLBody></component>
            </ClinicalDocument>
            """.getBytes(StandardCharsets.UTF_8);

    private CdaValidator validator() throws Exception {
        return new CdaValidator(Path.of("target/schema/schemas/hl7cdar2"), definitions);
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> issues(Map<String, Object> outcome) {
        assertEquals("OperationOutcome", outcome.get("resourceType"));
        return (List<Map<String, Object>>) outcome.get("issue");
    }

    @Test void missingProfileCannotPassFullValidation() throws Exception {
        var result = validator().validate(
                "<ClinicalDocument xmlns=\"urn:hl7-org:v3\"><templateId root=\"2.16.840.1.113883.10.20.22.1.1\"/></ClinicalDocument>"
                        .getBytes(StandardCharsets.UTF_8), true);
        assertTrue(issues(result).stream().anyMatch(i -> "not-supported".equals(i.get("code"))));
        assertTrue(issues(result).stream().anyMatch(i -> "structure".equals(i.get("code"))));
    }

    @Test void validCdaPassesXsdWithoutClaimingProfileCompliance() throws Exception {
        var result = validator().validate(VALID_XML, false);
        assertFalse(issues(result).stream().anyMatch(i -> List.of("error", "fatal").contains(i.get("severity"))),
                result.toString());
        assertTrue(issues(result).stream().anyMatch(i -> i.get("diagnostics").toString().contains("XSD-only")));
        assertTrue(issues(validator().validate(VALID_XML, true)).stream()
                .anyMatch(i -> "not-supported".equals(i.get("code"))));
    }

    @Test void externalEntitiesAndMalformedXmlAreRejected() throws Exception {
        for (String xml : List.of("<ClinicalDocument", """
                <!DOCTYPE ClinicalDocument [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
                <ClinicalDocument xmlns="urn:hl7-org:v3">&xxe;</ClinicalDocument>
                """, "<Patient/>")) {
            var result = validator().validate(xml.getBytes(StandardCharsets.UTF_8), false);
            assertEquals("error", issues(result).getFirst().get("severity"));
            assertFalse(result.toString().contains("root:x:"));
        }
    }

    @Test void schematronRunsActualRulesAndReportsLocations() throws Exception {
        Files.write(definitions.resolve("epic-ccda.xsl"), new SchematronTransformer().convertToXslt("""
                <schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
                  <ns prefix="c" uri="urn:hl7-org:v3"/>
                  <pattern id="synthetic"><rule context="c:ClinicalDocument">
                    <assert test="c:title" role="error">Synthetic title required</assert>
                    <assert test="c:languageCode" role="warning">Synthetic language required</assert>
                  </rule></pattern>
                </schema>
                """.getBytes(StandardCharsets.UTF_8)));
        var result = validator().validate("""
                <ClinicalDocument xmlns="urn:hl7-org:v3">
                  <templateId root="2.16.840.1.113883.10.20.22.1.1"/>
                </ClinicalDocument>
                """.getBytes(StandardCharsets.UTF_8), true);
        assertTrue(issues(result).stream().anyMatch(i -> "warning".equals(i.get("severity"))));
        assertTrue(issues(result).stream().anyMatch(i -> i.get("diagnostics").toString().contains("Synthetic title required")));
        assertFalse(issues(result).stream().anyMatch(i -> "not-supported".equals(i.get("code"))));
    }

    @Test void classifiesOnlyRecognizedDocumentTemplates() throws Exception {
        var document = CdaValidator.parse("""
                <ClinicalDocument xmlns="urn:hl7-org:v3">
                  <templateId root="1.2.40.0.34.6.0.11.0.5.0.3"/>
                </ClinicalDocument>
                """.getBytes(StandardCharsets.UTF_8));
        assertEquals("at-arztbrief", CdaValidator.detectProfile(document));
    }

    @Test void schematronCannotReadExternalDocuments() throws Exception {
        Path secret = definitions.resolve("secret.xml");
        Files.writeString(secret, "<secret>not-for-validation</secret>");
        for (String expression : List.of(
                "doc('" + secret.toUri() + "')/secret = 'not-for-validation'",
                "unparsed-text('" + secret.toUri() + "') != ''",
                "exists(collection('" + secret.toUri() + "'))")) {
            Files.write(definitions.resolve("epic-ccda.xsl"), new SchematronTransformer().convertToXslt("""
                <schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
                  <ns prefix="c" uri="urn:hl7-org:v3"/>
                  <pattern id="external"><rule context="c:ClinicalDocument">
                    <assert test="%s">External document unavailable</assert>
                  </rule></pattern>
                </schema>
                """.formatted(expression).getBytes(StandardCharsets.UTF_8)));
            assertThrows(Exception.class, () -> validator().validate(VALID_XML, true));
        }
    }

    @Test void standaloneSchematronAndXsdCanPassTogether() throws Exception {
        Files.write(definitions.resolve("epic-ccda.xsl"), new SchematronTransformer().convertToXslt("""
                <schema xmlns="http://purl.oclc.org/dsdl/schematron" queryBinding="xslt2">
                  <ns prefix="c" uri="urn:hl7-org:v3"/>
                  <pattern id="synthetic"><rule context="c:ClinicalDocument">
                    <assert test="c:title">Synthetic title required</assert>
                  </rule></pattern>
                </schema>
                """.getBytes(StandardCharsets.UTF_8)));
        var result = validator().validate(VALID_XML, true);
        assertFalse(issues(result).stream().anyMatch(i -> List.of("error", "fatal").contains(i.get("severity"))),
                result.toString());
    }

    @Test void stylesheetIncludesCannotAccessExternalFiles() throws Exception {
        Files.writeString(definitions.resolve("epic-ccda.xsl"), """
                <xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform" version="2.0">
                  <xsl:include href="http://127.0.0.1/forbidden"/>
                </xsl:stylesheet>
                """);
        assertThrows(IllegalArgumentException.class, this::validator);
    }

    @Test void extensionErrorsAreAccompaniedByAnExplicitCoverageWarning() throws Exception {
        byte[] xml = new String(VALID_XML, StandardCharsets.UTF_8)
                .replace("<title>", "<sdtc:unknown xmlns:sdtc=\"urn:hl7-org:sdtc\"/><title>")
                .getBytes(StandardCharsets.UTF_8);
        var result = validator().validate(xml, false);
        assertTrue(issues(result).stream().anyMatch(i -> "warning".equals(i.get("severity"))
                && i.get("diagnostics").toString().contains("not proof of profile violations")));
        assertTrue(issues(result).stream().anyMatch(i -> "error".equals(i.get("severity"))));
    }
}
