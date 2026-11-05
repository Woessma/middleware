package ch.omnilink.validation;

import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.validation.ValidationOptions;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import org.hl7.fhir.common.hapi.validation.support.NpmPackageValidationSupport;
import org.hl7.fhir.r4.model.OperationOutcome;
import org.projecthusky.fhir.emed.ch.epr.validator.ChEmedEprHapiValidator;

public class OfflineFhirValidator extends ChEmedEprHapiValidator {
    public static final String VACD_PROFILE =
            "http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration|6.0.0";
    protected final FhirContext context;
    private final ObjectMapper json = new ObjectMapper();

    public OfflineFhirValidator() throws IOException {
        this(FhirContext.forR4());
    }

    private OfflineFhirValidator(FhirContext context) throws IOException {
        super(context);
        this.context = context;
        this.logValidationOutcome = false;
        var packages = new NpmPackageValidationSupport(context);
        packages.loadPackageFromClasspath("/package/hl7.terminology.r4#7.0.1.tgz");
        packages.loadPackageFromClasspath("/package/hl7.fhir.uv.extensions.r4#5.2.0.tgz");
        packages.loadPackageFromClasspath("/package/ch.fhir.ig.ch-vacd#6.0.0.tgz");
        chain.addValidationSupport(packages);
        try (var definition = getClass().getResourceAsStream("/definitions/iso21090-codedString.json")) {
            if (definition == null) throw new IOException("CH Core codedString dependency unavailable");
            var profile = context.newJsonParser().parseResource(org.hl7.fhir.r4.model.StructureDefinition.class,
                    new String(definition.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
            if (!"http://hl7.org/fhir/StructureDefinition/iso21090-codedString".equals(profile.getUrl())
                    || !"5.3.0-ballot-tc1".equals(profile.getVersion())) {
                throw new IOException("Unexpected CH Core codedString dependency");
            }
            prepopulatedValidationSupport.addStructureDefinition(profile);
        }
        if (chain.fetchStructureDefinition(VACD_PROFILE) == null) {
            throw new IOException("CH-VACD 6.0.0 document profile unavailable");
        }
    }

    public synchronized ObjectNode validateVacd(JsonNode bundle) throws IOException {
        if (bundle == null || !bundle.isObject()
                || !"Bundle".equals(bundle.path("resourceType").asText())
                || !"document".equals(bundle.path("type").asText())) {
            throw new IllegalArgumentException("A CH-VACD document Bundle is required");
        }
        var outcome = validateFinalJson(bundle, VACD_PROFILE);
        outcome.withArray("issue").addObject().put("severity", "information")
                .put("code", "informational")
                .put("diagnostics", "Husky 3.5.0; CH-VACD 6.0.0; CH Core 6.0.0; local terminology packages. "
                        + "Instance validation only; no clinical vaccination recommendation or storage.")
                .putArray("extension").addObject().put("url", "urn:omnilink:validation:profile")
                .put("valueString", VACD_PROFILE);
        return outcome;
    }

    protected synchronized ObjectNode validateFinalJson(JsonNode bundle, String profile) throws IOException {
        // Validate the exact JSON returned or submitted, not a reparsed/reserialized proxy.
        var result = validator.validateWithResult(bundle.toString(), new ValidationOptions().addProfile(profile));
        var outcome = (OperationOutcome) result.toOperationOutcome();
        for (var resourceProfiles : bundle.findValues("meta")) {
            for (var declared : resourceProfiles.path("profile")) {
                if (declared.isTextual() && chain.fetchStructureDefinition(declared.asText()) == null) {
                    outcome.addIssue().setSeverity(OperationOutcome.IssueSeverity.ERROR)
                            .setCode(OperationOutcome.IssueType.NOTSUPPORTED)
                            .setDiagnostics("Declared profile unavailable in offline validator: " + declared.asText())
                            .addExtension().setUrl("urn:omnilink:validation:profile")
                            .setValue(new org.hl7.fhir.r4.model.StringType(declared.asText()));
                }
            }
        }
        if (!outcome.hasIssue()) {
            outcome.addIssue().setSeverity(OperationOutcome.IssueSeverity.INFORMATION)
                    .setCode(OperationOutcome.IssueType.INFORMATIONAL).setDiagnostics("FHIR profile validation passed");
        }
        var response = (ObjectNode) json.readTree(context.newJsonParser().encodeResourceToString(outcome));
        addProfileContext(response, bundle, profile);
        return response;
    }

    static void addProfileContext(ObjectNode outcome, JsonNode bundle, String profile) {
        outcome.withArray("extension").addObject()
                .put("url", "urn:omnilink:validation:profile").put("valueString", profile);
        var resourcePath = java.util.regex.Pattern.compile("^Bundle\\.entry\\[(\\d+)\\]\\.resource");
        for (var issue : outcome.path("issue")) {
            var profiles = new java.util.TreeSet<String>();
            for (String field : java.util.List.of("expression", "location")) {
                for (var location : issue.path(field)) {
                    var match = resourcePath.matcher(location.asText());
                    if (!match.find()) continue;
                    int index;
                    try {
                        index = Integer.parseInt(match.group(1));
                    } catch (NumberFormatException ex) {
                        continue;
                    }
                    var resource = bundle.path("entry").path(index).path("resource");
                    // A contained resource can declare different profiles; do not attribute its issue to its parent.
                    if (location.asText().substring(match.end()).contains(".contained")) continue;
                    for (var declared : resource.path("meta").path("profile")) {
                        if (declared.isTextual()) profiles.add(declared.asText());
                    }
                }
            }
            for (var declared : profiles) {
                ((ObjectNode) issue).withArray("extension").addObject()
                        .put("url", "urn:omnilink:validation:context-profile").put("valueString", declared);
            }
        }
    }
}
