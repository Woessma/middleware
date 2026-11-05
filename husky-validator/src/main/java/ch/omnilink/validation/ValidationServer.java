package ch.omnilink.validation;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;

public final class ValidationServer {
    static final int MAX_BYTES = 5 * 1024 * 1024;
    private static final ObjectMapper JSON = new ObjectMapper();

    public static void main(String[] args) throws Exception {
        var validator = new CdaValidator(Path.of("/app/schema/schemas/hl7cdar2"), Path.of("/definitions"));
        var pmlc = new PmlcService();
        var server = HttpServer.create(new InetSocketAddress(8091), 16);
        server.setExecutor(Executors.newFixedThreadPool(2));
        server.createContext("/health", exchange -> {
            if (!"/health".equals(exchange.getRequestURI().getPath())) {
                send(exchange, 404, failure("not-found", "Unknown endpoint"));
            } else if (!"GET".equals(exchange.getRequestMethod())) {
                send(exchange, 405, failure("not-supported", "GET required"));
            } else {
                send(exchange, 200, Map.of("status", "ok", "service", "husky-cda-validator",
                        "huskyVersion", "3.5.0", "schema", "CDA R2",
                        "schematronProfiles", validator.availableProfiles(),
                        "pmlcProfile", PmlcService.DOCUMENT_PROFILE,
                        "vacdProfile", OfflineFhirValidator.VACD_PROFILE));
            }
        });
        server.createContext("/vacd/validate", exchange -> {
            try {
                if (!"/vacd/validate".equals(exchange.getRequestURI().getPath())) {
                    send(exchange, 404, failure("not-found", "Unknown endpoint"));
                } else if (!"POST".equals(exchange.getRequestMethod())) {
                    send(exchange, 405, failure("not-supported", "POST required"));
                } else {
                    byte[] body = exchange.getRequestBody().readNBytes(MAX_BYTES + 1);
                    if (body.length > MAX_BYTES) {
                        send(exchange, 413, failure("too-costly", "FHIR input exceeds 5 MiB"));
                    } else {
                        var outcome = pmlc.validateVacd(JSON.readTree(body));
                        boolean errors = false;
                        for (var issue : outcome.path("issue")) {
                            errors |= List.of("error", "fatal").contains(issue.path("severity").asText());
                        }
                        send(exchange, errors ? 422 : 200, JSON.convertValue(outcome,
                                new com.fasterxml.jackson.core.type.TypeReference<Map<String, Object>>() {}));
                    }
                }
            } catch (IllegalArgumentException | com.fasterxml.jackson.core.JsonProcessingException ex) {
                System.err.println("VACD input rejected: " + ex.getClass().getSimpleName());
                send(exchange, 400, failure("invalid", "A valid CH-VACD document Bundle is required"));
            } catch (Exception ex) {
                System.err.println("VACD validation failed: " + ex.getClass().getSimpleName());
                send(exchange, 503, failure("exception", "VACD validation engine failed; validation not completed"));
            }
        });
        server.createContext("/emed/pmlc", exchange -> {
            try {
                if (!"/emed/pmlc".equals(exchange.getRequestURI().getPath())) {
                    send(exchange, 404, failure("not-found", "Unknown endpoint"));
                } else if (!"POST".equals(exchange.getRequestMethod())) {
                    send(exchange, 405, failure("not-supported", "POST required"));
                } else {
                    byte[] body = exchange.getRequestBody().readNBytes(MAX_BYTES + 1);
                    if (body.length > MAX_BYTES) {
                        send(exchange, 413, failure("too-costly", "FHIR input exceeds 5 MiB"));
                    } else {
                        var response = pmlc.generate(JSON.readTree(body));
                        byte[] bytes = JSON.writeValueAsBytes(response);
                        exchange.getResponseHeaders().set("Content-Type", "application/json");
                        exchange.getResponseHeaders().set("Cache-Control", "no-store");
                        exchange.sendResponseHeaders(200, bytes.length);
                        try (var output = exchange.getResponseBody()) { output.write(bytes); }
                    }
                }
            } catch (IllegalArgumentException | com.fasterxml.jackson.core.JsonProcessingException ex) {
                System.err.println("PMLC input rejected: " + ex.getClass().getSimpleName());
                send(exchange, 400, failure("invalid", "Invalid PMLC source data"));
            } catch (Exception ex) {
                System.err.println("PMLC generation failed: " + ex.getClass().getSimpleName());
                send(exchange, 503, failure("exception", "PMLC generation or validation failed"));
            }
        });
        server.createContext("/validate", exchange -> {
            try {
                if (!"/validate".equals(exchange.getRequestURI().getPath())) {
                    send(exchange, 404, failure("not-found", "Unknown endpoint"));
                } else if (!"POST".equals(exchange.getRequestMethod())) {
                    send(exchange, 405, failure("not-supported", "POST required"));
                } else {
                    String level = exchange.getRequestHeaders().getFirst("X-Validation-Level");
                    if (level == null) level = "full";
                    if (!List.of("xsd", "full").contains(level)) {
                        send(exchange, 400, failure("invalid", "Validation level must be xsd or full"));
                        return;
                    }
                    byte[] body = exchange.getRequestBody().readNBytes(MAX_BYTES + 1);
                    if (body.length > MAX_BYTES) {
                        send(exchange, 413, failure("too-costly", "CDA exceeds 5 MiB"));
                    } else if (body.length == 0) {
                        send(exchange, 400, failure("required", "CDA content required"));
                    } else {
                        send(exchange, 200, validator.validate(body, "full".equals(level)));
                    }
                }
            } catch (Exception ex) {
                System.err.println("CDA validation failed: " + ex.getClass().getSimpleName());
                send(exchange, 503, failure("exception", "CDA validation engine failed; validation not completed"));
            }
        });
        server.start();
        System.out.println("Internal Husky CDA validator listening on 8091");
    }

    static Map<String, Object> failure(String code, String message) {
        return CdaValidator.outcome(List.of(CdaValidator.issue("error", code, message, "Husky service", "/")));
    }

    static void send(HttpExchange exchange, int status, Map<String, Object> body) throws IOException {
        byte[] bytes = JSON.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/fhir+json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.sendResponseHeaders(status, bytes.length);
        try (var output = exchange.getResponseBody()) {
            output.write(bytes);
        }
    }
}
