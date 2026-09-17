# Roadmap

Stand: 2026-09-10

## Phase 0 (aktuell)

- CDA -> UMZH Convert mit Workflow-Stages (`initial`, `updated`, `completed`)
- Sandbox-kompatible Zielreferenzen (`target=sandbox-placer`)
- CDA -> UMZH Send (Convert + Versandreport)
- EPIC-CDA Medikation End-to-End (`cda/import` -> FHIR -> `from-server`) stabilisiert
- EPIC `recordTarget` Patientdaten erweitert
- Medikationsexport mit `effectiveTime`/`doseQuantity` und bereinigten Notizen umgesetzt
- EPIC-Medikationsnarrative auf CDA-EPIC-kompatibles Listenlayout vereinheitlicht
- CH-EMED-nahes Medication-Enrichment (optional `form`, `ingredient`, `strength` aus Mapping) eingebaut
- Default fuer `/fhir/medications/epic-cda/from-server` auf `count=100` gesetzt
- CH VACD Immunization Administration Convert mit CH-VACD-Dokumentprofil, Composition-first und Impfcode-Kette umgesetzt
- FHIR-Import-Stabilisierung für Einzelressourcen und Dokumentbundles umgesetzt
- eMediplan-PDF-/Bildimport ueber QR-Code umgesetzt
- `PrscbBy` mit GS1-Modulo-10-Pruefung auf CH-Core-Practitioner und GLN-OID `urn:oid:2.51.1.3` abgebildet
- refdata.ch Partner-API fuer optionale GLN-Pruefung sowie Name-/Adressanreicherung angebunden
- FHIR Query Client zeigt den Verordner mit GLN oder dem Hinweis `GLN: nicht vorhanden`
- Matrix Import Bot fuer eMediplan-PDF/Bild und CDA-XML mit blockierender Absender-Patienten-Pruefung umgesetzt
- Private Zwei-Personen-Raeume und Self-Service-Identitaetsverwaltung fuer den Matrix-Bot umgesetzt
- EchoSOS-QR/PKPass-Import mit automatischer `$everything`-Abfrage und Notfallansicht umgesetzt
- FHIR-Kontaktmodell fuer `Patient.contact`, `RelatedPerson` und PCP-CareTeam dokumentiert und visualisiert
- Blutgruppe, Schwangerschaftsstatus sowie kategorisierte Labor-/Vital-/Sozialobservations visualisiert

## Phase 1

- CDA → FHIR
- CDA → CH VACD Immunization Administration Document
- HL7v2 → FHIR

## Phase 2

- Clinical Notes
- DocumentReference
- Binary
- DiagnosticReport

## Phase 3

- US Core Unterstützung

## Phase 4

- FHIR → CDA
- FHIR → HL7v2

## Phase 5

- Kafka Integration
- RabbitMQ Integration
- Microservice Aufteilung

## CH VACD Folgearbeiten

- Validator-Setup um `ch.fhir.ig.ch-vacd#7.0.0-ballot` erweitern
- Swissmedic-Codings produktbezogen aus der offiziellen CH-VACD-ValueSet übernehmen
- Vollständige CDA-Beispieldokumente gegen den CH-VACD-Validator prüfen
