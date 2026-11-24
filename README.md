# Python FHIR Middleware

Dieses Repository enthält die Python-Middleware, die klinische Daten für FHIR
aufbereitet und transformiert. BridgeLink übernimmt Orchestrierung und Routing;
HAPI FHIR ist die maßgebliche Datenquelle für gespeicherte Ressourcen.

## Dokumentation

- [Architektur und Datenflüsse](docs/architecture.md)
- [API-Endpunkte und Verhalten](docs/ENDPOINTS.md)
- [Test-Client und Use-Cases](docs/TEST-CLIENT.md)
- [HAPI-MDM-Verhalten](docs/hapi-mdm.md)
- [Architekturentscheidungen](docs/decisions/)
- [Agent-Anweisungen](AGENTS.md)

## Repository-Struktur

- `app/` — Middleware-Anwendung und Terminologiedaten
- `docs/` — Projekt-, API-, Architektur- und Fachdokumentation
- `bridgelink/` — BridgeLink-Konfiguration und Codevorlagen
- `husky-validator/` — interner CDA-Validator mit Dokumentation
