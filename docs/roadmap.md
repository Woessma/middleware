# Roadmap

Stand: 2026-11-25

## In Untersuchung: HAPI-MDM-Identifier-Übernahme

- Bestätigte Source-Identifier mit Herkunft am Golden Patient führen; CDA- und
  VACD-Schreibpfade sowie bestehende Patienten berücksichtigen.
- Isolierte Outbox-/Sperrexperimente fortführen; Wiederanlauf und Schutz aller
  relevanten Leser bei ausstehendem oder fehlgeschlagenem Stand nachweisen.
- Technische CDA-Quelle anhand eines eindeutigen EPIC-Schlüssels pro
  Namensraum anbinden; fehlende oder mehrdeutige Schlüssel blockieren.
- Kein Deployment vor vollständiger Prüfung von Lifecycle, Bestandsabgleich,
  Betrieb und Migration. Convert und Prepare bleiben schreibfrei.

## Aktuelle Ergaenzung: Automatisierter Refdata-Partner-Refresh

- `POST /admin/api/refdata/refresh` laedt das offizielle Partner-Zip von api.refdata.ch, validiert NAT/JUR und ersetzt die Dateien atomar im persistenten Volume `refdata-data`
- Refdata-XMLs aus dem Docker-Image entfernt; GLN-Anreicherung nutzt tagesaktuelle Volume-Daten, SQLite-Index wird automatisch neu aufgebaut
- Taeglicher Trigger ueber BridgeLink-Channel `Refdata_Partner_Refresh` (02:00 UTC = 03:00 CET) mit alertbarem Fehlerverhalten; Snapshot versioniert unter `bridgelink/`
- Geplante separate `omnilink_refdata`-PostgreSQL-Datenbank bleibt als langfristige Loesung im Backlog

## Vorherige Ergaenzung: Beratende CH-EMED-Validierung fuer eMediplan

- `POST /emediplan/validate` fuer Text/JSON/CHMED16A und QR aus PDF/Bild mit eigenen Werkbank-Use-Cases umgesetzt
- Pruefkopie wird in die CH-EMED-Struktur transformiert (contained Medication, UUID-Identifier, PractitionerRole) und intern mit HAPI geprueft; Realplan 0 Fehler
- Convert/Import liefern unveraendert die CH-Core-Struktur fuer Upsert und Dublettenabgleich; blockierende Importpruefung unveraendert scharf
- Datenqualitaet verbessert: strukturierte refdata-Namen (ch-pract-1), `dateAsserted` aus Plan-`Dt`, `Auth`-GLN als informationSource-Fallback, GTIN zusaetzlich als `urn:oid:2.51.1.1`, Narrative im Convert-Bundle
- Erkenntnisse auf alle Use Cases uebertragen: CDA-Mapper mit OID-GTIN-Aufloesung und -Zwillingscodings, Dublettenabgleich auch per OID-GTIN, EchoSOS-Narrative

## Vorherige Ergaenzung: Validierung und Medikationsvorschau

- Interner Husky-Dienst und zusaetzliche VACD-Pruefung mit stabilen 6.0.0-Profilen deployt
- PMLC-FHIR-Vorschau ohne Speicherung umgesetzt; PDF/A/QR und finale EPR-Konformitaet offen
- Importmapping getrennt von EPR-Ausgabetransformation und verpflichtender finaler Importpruefung
- Werkbank zeigt Fehler/Warnungen mit expliziter Profilangabe oder gekennzeichnetem Kontext
- Noch erforderlich: CDA-Gateway-Redeploy auf `/cda/prepare` und erneute Original-CDA-Abnahme

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
- EchoSOS-QR/PKPass-Import mit SNOMED-Allergien, Reaktionsmanifestationen, SNOMED-Vorgeschichte, bedingtem Organspende-Consent, Blutgruppe und bis zu drei Notfallkontakten umgesetzt; Transaction-Bundle-Write läuft über BridgeLink, `$everything` ist ein separater Folgeaufruf
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

- Stabile CH-VACD-/CH-Core-Version 6.0.0 beibehalten; Versionswechsel separat pruefen,
  keine automatische Umstellung auf `7.0.0-ballot`
- Swissmedic-Codings produktbezogen aus der offiziellen CH-VACD-ValueSet übernehmen
- Vollständige CDA-Beispieldokumente gegen den CH-VACD-Validator prüfen
