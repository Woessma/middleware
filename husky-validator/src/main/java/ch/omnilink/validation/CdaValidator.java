package ch.omnilink.validation;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.HashMap;
import com.helger.schematron.svrl.SVRLHelper;
import com.helger.schematron.xslt.SchematronResourceXSLT;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamSource;
import org.projecthusky.validation.service.schema.XmlSchemaValidator;
import org.projecthusky.validation.service.schematron.SchematronReport;
import javax.xml.transform.TransformerException;
import net.sf.saxon.jaxp.TransformerImpl;
import net.sf.saxon.trans.XPathException;
import net.sf.saxon.lib.Feature;
import org.w3c.dom.Document;
import org.w3c.dom.bootstrap.DOMImplementationRegistry;
import org.w3c.dom.ls.DOMImplementationLS;
import org.xml.sax.ErrorHandler;
import org.xml.sax.SAXParseException;

public final class CdaValidator {
    static final String PROFILE_EXTENSION = "urn:omnilink:validation:profile";
    private final XmlSchemaValidator schema;
    private final Map<String, SchematronResourceXSLT> schematrons;

    public CdaValidator(Path schemaDirectory, Path definitions) throws Exception {
        Path root = schemaDirectory.toRealPath();
        var implementation = (DOMImplementationLS) DOMImplementationRegistry.newInstance()
                .getDOMImplementation("LS");
        schema = new XmlSchemaValidator(new StreamSource(root.resolve("CDA.xsd").toFile()),
                false, false, (type, namespace, publicId, systemId, baseUri) -> {
                    try {
                        Path base = baseUri == null ? root : Path.of(java.net.URI.create(baseUri)).getParent();
                        Path included = base.resolve(systemId).normalize().toRealPath();
                        if (!included.startsWith(root)) {
                            throw new IllegalArgumentException("Schema include outside packaged schema");
                        }
                        var input = implementation.createLSInput();
                        input.setSystemId(included.toUri().toString());
                        input.setBaseURI(included.getParent().toUri().toString());
                        input.setByteStream(new ByteArrayInputStream(Files.readAllBytes(included)));
                        return input;
                    } catch (IOException ex) {
                        throw new IllegalArgumentException("Packaged schema include unavailable", ex);
                    }
                });
        var installed = new HashMap<String, SchematronResourceXSLT>();
        for (String profile : List.of("epic-ccda", "at-arztbrief")) {
            Path rules = definitions.resolve(profile + ".xsl");
            if (Files.isRegularFile(rules)) {
                installed.put(profile, secureSchematron(rules));
            }
        }
        schematrons = Map.copyOf(installed);
    }

    public List<String> availableProfiles() {
        return schematrons.keySet().stream().sorted().toList();
    }

    public synchronized Map<String, Object> validate(byte[] xml, boolean full) throws Exception {
        var issues = new ArrayList<Map<String, Object>>();
        Document document;
        try {
            document = parse(xml);
        } catch (SAXParseException ex) {
            issues.add(issue("error", "invalid", "XML parsing failed: " + ex.getMessage(),
                    "CDA XML", "Line " + ex.getLineNumber() + ", column " + ex.getColumnNumber()));
            return outcome(issues);
        }
        var element = document.getDocumentElement();
        if (!"ClinicalDocument".equals(element.getLocalName())
                || !"urn:hl7-org:v3".equals(element.getNamespaceURI())) {
            issues.add(issue("error", "invalid", "Expected HL7 v3 ClinicalDocument", "CDA XML", "/"));
            return outcome(issues);
        }
        var extensions = List.of("urn:hl7-org:sdtc", "urn:hl7-at:v3",
                "urn:ihe:pharm:medication", "urn:hl7-org:ips").stream()
                .filter(namespace -> document.getElementsByTagNameNS(namespace, "*").getLength() > 0)
                .toList();
        if (!extensions.isEmpty()) {
            issues.add(issue("warning", "not-supported",
                    "Base CDA R2 XSD does not cover these extensions: " + String.join(", ", extensions)
                            + ". Schema errors involving these extensions are not proof of profile violations.",
                    "CDA XSD coverage", "/ClinicalDocument"));
        }
        var report = schema.validate(new DOMSource(document));
        for (var error : report.getErrors()) {
            issues.add(issue("error", "structure", error.getMessage(), "CDA R2 XSD (Husky 3.5.0)", "/ClinicalDocument"));
        }
        for (var warning : report.getWarnings()) {
            issues.add(issue("warning", "structure", warning.getMessage(), "CDA R2 XSD (Husky 3.5.0)", "/ClinicalDocument"));
        }
        if (report.getFatalError() != null) {
            issues.add(issue("fatal", "structure", report.getFatalError().getMessage(),
                    "CDA R2 XSD (Husky 3.5.0)", "/ClinicalDocument"));
        }
        if (report.isValid()) {
            issues.add(issue("information", "informational", "CDA R2 schema validation passed",
                    "CDA R2 XSD (Husky 3.5.0)", "/ClinicalDocument"));
        }
        String profile = detectProfile(document);
        if (!full) {
            issues.add(issue("information", "informational",
                    "XSD-only check; no template/Schematron conformity asserted. Detected: " + profile,
                    profile, "/ClinicalDocument"));
        } else {
            var validator = schematrons.get(profile);
            if (validator == null) {
                issues.add(issue("error", "not-supported",
                        "Profile Schematron is not installed; full CDA profile validation is incomplete",
                        profile, "/ClinicalDocument/templateId"));
            } else {
                var svrl = validator.applySchematronValidationToSVRL(document, null);
                if (svrl == null) {
                    throw new IllegalStateException("Schematron produced no result");
                }
                var result = new SchematronReport();
                result.getActivePatternAndFiredRuleAndFailedAssert()
                        .addAll(svrl.getActivePatternAndFiredRuleAndFailedAssert());
                if (result.getFiredRules().isEmpty()) {
                    throw new IllegalStateException("Schematron produced no applicable rules");
                }
                for (var failed : result.getFailedAsserts()) {
                    String role = failed.getRole();
                    String severity = "warning".equalsIgnoreCase(role) || "warn".equalsIgnoreCase(role)
                            ? "warning" : "error";
                    issues.add(issue(severity, "invalid",
                            SVRLHelper.getAsString(SVRLHelper.getText(failed)), profile, failed.getLocation()));
                }
                for (var successful : result.getSuccessfulReports()) {
                    String role = successful.getRole();
                    String severity = "error".equalsIgnoreCase(role) || "fatal".equalsIgnoreCase(role)
                            ? "error" : "warning".equalsIgnoreCase(role) ? "warning" : "information";
                    issues.add(issue(severity, "processing",
                            SVRLHelper.getAsString(SVRLHelper.getText(successful)), profile, successful.getLocation()));
                }
                issues.add(issue("information", "informational",
                        "Schematron executed " + result.getFiredRules().size() + " rules",
                        profile, "/ClinicalDocument"));
            }
        }
        return outcome(issues);
    }

    private static SchematronResourceXSLT secureSchematron(Path rules) throws Exception {
        byte[] xslt = Files.readAllBytes(rules);
        Document stylesheet = parse(xslt);
        for (String directive : List.of("include", "import")) {
            if (stylesheet.getElementsByTagNameNS("http://www.w3.org/1999/XSL/Transform", directive).getLength() != 0) {
                throw new IllegalArgumentException("Schematron XSLT must be self-contained");
            }
        }
        var resource = SchematronResourceXSLT.fromByteArray(xslt);
        resource.setURIResolver((href, base) -> {
            throw new TransformerException("External Schematron document access prohibited");
        });
        resource.setEntityResolver((publicId, systemId) -> {
            throw new org.xml.sax.SAXException("External Schematron entity access prohibited");
        });
        resource.setErrorListener(new javax.xml.transform.ErrorListener() {
            public void warning(TransformerException ex) throws TransformerException { throw ex; }
            public void error(TransformerException ex) throws TransformerException { throw ex; }
            public void fatalError(TransformerException ex) throws TransformerException { throw ex; }
        });
        var provider = resource.getXSLTProvider();
        if (provider == null || !(provider.getXSLTTransformer() instanceof TransformerImpl transformer)) {
            throw new IllegalStateException("Secure Saxon Schematron engine unavailable");
        }
        var configuration = transformer.getUnderlyingController().getConfiguration();
        configuration.setBooleanProperty(Feature.ALLOW_EXTERNAL_FUNCTIONS, false);
        configuration.setUnparsedTextURIResolver((uri, encoding, config) -> {
            throw new XPathException("External Schematron text access prohibited");
        });
        configuration.setCollectionFinder((context, uri) -> {
            throw new XPathException("External Schematron collection access prohibited");
        });
        return resource;
    }

    static Document parse(byte[] xml) throws Exception {
        var factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
        factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
        factory.setXIncludeAware(false);
        factory.setExpandEntityReferences(false);
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        var builder = factory.newDocumentBuilder();
        builder.setErrorHandler(new ErrorHandler() {
            public void warning(SAXParseException ex) throws SAXParseException { throw ex; }
            public void error(SAXParseException ex) throws SAXParseException { throw ex; }
            public void fatalError(SAXParseException ex) throws SAXParseException { throw ex; }
        });
        return builder.parse(new ByteArrayInputStream(xml));
    }

    static String detectProfile(Document document) {
        boolean epic = false;
        boolean at = false;
        var children = document.getDocumentElement().getChildNodes();
        for (int i = 0; i < children.getLength(); i++) {
            if (children.item(i) instanceof org.w3c.dom.Element element
                    && "templateId".equals(element.getLocalName())
                    && "urn:hl7-org:v3".equals(element.getNamespaceURI())) {
                String root = element.getAttribute("root");
                epic |= root.equals("2.16.840.1.113883.10.20.22.1.1");
                at |= root.equals("1.2.40.0.34.6.0.11.0.5.0.3");
            }
        }
        if (epic && at) {
            return "unsupported";
        }
        return epic ? "epic-ccda" : at ? "at-arztbrief" : "unsupported";
    }

    static Map<String, Object> issue(String severity, String code, String text, String profile, String location) {
        return Map.of("severity", severity, "code", code, "diagnostics", text == null ? "Schematron issue without text" : text,
                "extension", List.of(Map.of("url", PROFILE_EXTENSION, "valueString", profile)),
                "expression", List.of(location == null ? "/ClinicalDocument" : location));
    }

    static Map<String, Object> outcome(List<Map<String, Object>> issues) {
        return Map.of("resourceType", "OperationOutcome", "issue", issues);
    }
}
