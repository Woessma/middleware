# BridgeLink - Project Memory

Stand: 2026-09-10

## Projektname

BridgeLink

## Vision

BridgeLink ist eine Healthcare-Integrationsplattform fuer die Transformation, Validierung, Orchestrierung und Speicherung klinischer Daten.

BridgeLink verbindet:

- KIS
- Praxissysteme
- Labor-Systeme
- FHIR-Plattformen

ueber standardisierte Schnittstellen.

---

## Zielarchitektur

Quellsystem
→ BridgeLink
→ Python Middleware
→ HAPI FHIR Lookup und Persistenz

---

## Komponenten

### BridgeLink

Verantwortlich fuer:

- Workflow-Orchestrierung
- Routing
- Monitoring
- Auftragssteuerung

### Python Middleware

Verantwortlich fuer:

- CDA-Parsing
- Domain-Transformation
- FHIR-Mapping
- FHIR-Bundle-Erzeugung
- HAPI-Lookup und Referenzaufloesung
- direkte Importvorbereitung fuer HAPI FHIR
- Bundle-Dedupe

### HAPI FHIR

Verantwortlich fuer:

- FHIR-Repository
- Source of Truth
- Ressourcenverwaltung

---

## Aktuelle Technologie

### Backend

- Python 3.12
- FastAPI

### Infrastruktur

- Docker
- Docker Compose

### Standards

- FHIR
- CH Core
- CDA

HL7v2-Strukturen sind im Repository angelegt, der aktive API-Pfad ist derzeit jedoch CDA-zentriert.

---

## Software-Architektur

Parser
→ Converter und Domain Layer
→ Mapper und Builder
→ FHIR Bundle und HAPI Integration

---

## Parser

### CDA

- Patient Parser
- Practitioner Parser
- Organization Parser
- Encounter Parser
- Section Parser

### HL7v2

- Verzeichnisstruktur vorhanden, aktuell nicht ueber die FastAPI-Endpunkte exponiert

---

## Domain Layer

Aktuelle Domaenenmodelle:

- Patient
- Practitioner
- Organization
- Encounter
- Clinical Note

---

## Builder

- CH Core Patient
- CH Core Practitioner
- CH Core PractitionerRole
- CH Core Organization
- CH Core Encounter
- DocumentReference
- Binary
- Observation

---

## Mapper

- Allergy
- CareTeam
- Condition
- Consent
- Goal
- Immunization
- Laboratory
- Medication
- Organization
- Procedure
- Vital Signs

Clinical Notes werden nicht ueber einen klassischen Mapper, sondern ueber die Clinical-Note-Extraktion und DocumentReference/Binary-Builder umgesetzt.

---

## Services

- CDA Bundle Service
- Patient Service
- Practitioner Service
- Organization Service
- UMZH Convert Service
- UMZH Send Service

## Middleware-Implementierung

- Python-FastAPI-Anwendung aus `app/main.py`
- CDA-Parsing ueber `app/parser/cda/*.py`
- Clinical-Note-Extraktion ueber `app/converter/clinical_note_extractor.py`
- CH-Core- und DocumentReference-Builder in `app/builders/*.py`
- FHIR-Bundle-Assembly mit `build_bundle_entry()` und `cda_to_fhir_bundle()`
- HAPI-FHIR-Integration ueber HTTP-Requests zum FHIR-Server
- Bundle-Dedupe fuer `POST` anhand Identifiern oder Payload-Hash
- Import-Stabilisierung fuer Einzelressourcen und Dokumentbundles

## Deployment und Infrastruktur

- Docker-Compose-Service `middleware` in `docker-compose.yml`
- verwendet das externe Netzwerk `fhir-server_fhir-net`
- bindet an internen Port `8000`
- FHIR-Backend: `http://fhir-server:8080/fhir`
- Anforderungen in `requirements.txt`:
  - fastapi
  - uvicorn
  - requests
  - python-multipart

---

## Duplicate-Check-Strategie

Vor Import nach HAPI FHIR:

- Patient-Matching anhand Identifier
- Practitioner-Matching anhand Identifier
- Organization-Matching anhand Identifier
- fuer Practitioner und Organization erfolgt Create inzwischen deterministisch per stabilem `PUT ResourceType/{uuid5}` statt per offenem `POST`
- bei Mehrfachtreffern auf bestehende Practitioner oder Organizations wird ein kanonischer Datensatz deterministisch bevorzugt
- Observation- und Procedure-Dedupe auf Bundle- oder Mapper-Ebene
- fuer `POST` wird nicht mehr nur nach `(method, url)` dedupliziert, sondern nach fachlicher Identitaet oder Payload-Hash
- einzelne FHIR-Ressourcen werden vor dem Import automatisch als Transaction-Bundle verpackt
- Dokumentbundles (`Bundle.type=document`) werden vor dem Import als Transaction-Bundle vorbereitet
- fehlende `entry.request`-Angaben werden aus Ressourcentyp und ID als `PUT` oder `POST` abgeleitet
- fuer `PUT` bleibt Dedupe anhand `(method, url)` aktiv
- bei vorhandenem Identifier erfolgt Aktualisierung per `PUT ResourceType/{id}` nach Server-Lookup statt Query-Conditional-URL
- Procedure-Mapping nutzt gemeinsamen Kontext pro Importlauf, um echte In-Run-Doppler frueh zu verwerfen

Ziel:

Vermeidung doppelter Ressourcen und idempotente FHIR-Imports.

---

## API-Endpunkte

### CDA

- `POST /cda/debug` — detaillierte CDA-Analyse im Debug-Modus
- `POST /cda/convert` — konvertiert CDA zu einem FHIR-Transaction-Bundle
- `POST /cda/import` — importiert das erzeugte Bundle in HAPI FHIR
- `POST /emediplan/import-bundle` — stabilisiert und importiert ein einzelnes FHIR-Resource-Objekt oder Bundle in HAPI FHIR
- `POST /cda/umzh/convert` — konvertiert CDA in UMZH-Workflow-Bundle mit Stages `initial|updated|completed`
- `POST /cda/umzh/send` — kombiniert UMZH-Convert mit Versand an ein Ziel-FHIR-System und liefert einen Versandreport
- `POST /cda/etoc/convert` — erzeugt einen CH-eTOC-orientierten `Bundle.type=document`-Pfad (Composition zuerst, inkl. Order-Referral/Purpose-Sections)
- `POST /cda/vacd/convert` — erzeugt ein CH-VACD Immunization Administration Document (`Bundle.type=document`, Composition zuerst)

### eMediplan

- `POST /emediplan/convert` und `POST /emediplan/import` akzeptieren CHMED16A-Text sowie PDF/Bild mit QR-Code.
- `POST /emediplan/qr/convert` und `POST /emediplan/qr/import` sind die expliziten QR-Dateipfade.
- `Medicaments[].PrscbBy` enthaelt laut CHMED16A entweder GLN oder Bezeichnung des Verordners.
- Gueltige GLNs werden per GS1 Modulo 10 geprueft und als CH-Core-Practitioner mit `identifier.system=urn:oid:2.51.1.3` erzeugt.
- `app/services/refdata_service.py` fragt die refdata.ch Partner SOAP API best-effort ab und ergaenzt Name und Adresse; fehlende Konfiguration, Fehler oder nicht gefundene GLNs blockieren den Import nicht.
- Nicht als GLN erkennbare `PrscbBy`-Werte bleiben als `MedicationStatement.informationSource.display` erhalten.
- Das separate Top-Level-Feld `Auth` ist der Dokumentautor und wird nicht als Verordner-GLN interpretiert.

### Metadata

- `GET /metadata` — nur im Debug-Modus verfuegbar

### CH VACD Convert

Der CH-VACD-Pfad erzeugt ein Dokument nach CH VACD 1.0.0. Für den openEHR-basierten Versand wird die offizielle Definition https://fhir.ch/ig/ch-vacd/1.0.0/immunization-administration-document.html verwendet. Das Bundle trägt das offizielle CH-VACD-Dokumentprofil; die erste Ressource ist eine Composition mit dem CH-VACD-Composition-Profil. Immunizations tragen das CH-VACD-Immunization-Profil.

Der Pfad bereinigt generische CDA-Inhalte und behält nur Ressourcen, die für das Immunization-Administration-Dokument benötigt werden. Die Patient- und Impfungsreferenzen werden auf die jeweiligen Bundle-`fullUrl`s aufgelöst. Bekannte Impfprodukte werden in `vaccineCode.coding` mit CVX, SNOMED CT und Swissmedic abgebildet.

### Test-Endpunkte

- `GET /test/patient` — testet Patient-Import und Lookup
- `GET /test/organization` — testet Organization-Import und Lookup

---

## Aktueller Ausbaustand

Vorhanden:

- CDA-Parsing
- HL7v2-Grundstruktur im Repository
- CH-Core-Builder
- Clinical-Note-Extraktion
- DocumentReference- und Binary-Erzeugung
- FHIR-Bundle-Erstellung
- HAPI-Lookup sowie Create- und Update-Integration fuer Referenzressourcen
- Patient-, Practitioner- und Organization-Service-Implementierung
- Fehlerbehandlung bei XML-Parsing und FHIR-Server-Antworten

---

## Aktuelle Roadmap

### Phase 1

- CDA → FHIR
- Referenzressourcen-Lookup und idempotenter Import

### Phase 2

- Clinical Notes
- DocumentReference
- Binary
- DiagnosticReport

Clinical Notes, DocumentReference, Binary und ein erstes UMZH-orientiertes DiagnosticReport-Mapping sind umgesetzt.

## Letzte Arbeiten

- UMZH-Workflow erweitert: `workflow_stage=initial|updated|completed` (inkl. Questionnaire und QuestionnaireResponse in spaeteren Stages)
- UMZH-Targeting erweitert: `target=sandbox-placer` erzeugt sandbox-kompatible absolute Referenzen
- Neuer Endpoint `POST /cda/umzh/send` implementiert (Convert + Versand per `PUT ResourceType/{id}` mit Ergebnis je Ressource)
- Tests erweitert: Convert-Stages, Sandbox-Target und Send-Service sind automatisiert abgesichert
- UMZH-Workflow erweitert: DiagnosticReport wird jetzt als Teil des Referral-Bundles erzeugt (`basedOn` -> ServiceRequest, `result` -> Observation, optional `presentedForm` aus DocumentReference)
- Domain/Builder-Layer erweitert: `ServiceRequest`, `Task` und `DiagnosticReport` sind als dedizierte Domain- und Builder-Bausteine implementiert und im UMZH-Convert-Service verdrahtet
- CH eTOC v3.0.1 im Blick: ServiceRequest wird mit zusaetzlichem CH-eTOC-Profil (`http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-servicerequest`) markiert
- Zweiter Konvertierungspfad umgesetzt: `cda_to_etoc_document_bundle()` plus Endpoint `POST /cda/etoc/convert` fuer CH-eTOC-Dokument-Bundles (`type=document`, Composition-first, CH-eTOC-Profile auf Bundle/Composition)
- CH-eTOC Observation-Profilierung im Dokumentpfad umgesetzt: vorhandene diagnostische Observations werden heuristisch auf CH-eTOC-Profile gemappt (Lab/Pathology/Radiology/Cardiology), initial abgesichert fuer Lab-Observation
- Server-basierter Abnahme-Check ergaenzt: `app/scripts/etoc_acceptance_check.py` prueft CapabilityStatement, `/cda/etoc/convert`, Bundle-Shape, `$validate` und optional Persistenz gegen den Ziel-FHIR-Server
- CI erweitert (Mono-Repo): separater Workflow fuer `fhir-middleware` (Python-Tests) und separater Workflow fuer `fhir-server` (docker-compose + Nginx-Konfigurationschecks + Pflicht-IG-Keys)
- Isolierter Matrix-Stack im Repo angelegt: `fhir-server/matrix` mit eigenem Compose, `.env.example`, Nginx-vHost-Beispiel und Betriebs-README (keine Kollision mit FHIR-Ports)
- Produktives Nginx erweitert: Matrix-Endpunkte (`/_matrix`, `/_synapse/client`, `/.well-known/matrix/*`) auf `matrix-synapse:8008` geroutet; Synapse zusaetzlich im `fhir-server_fhir-net` zur Erreichbarkeit durch den FHIR-Nginx
- Stabilisierung: Matrix-Proxy in Nginx auf `127.0.0.1:8008` umgestellt, damit Nginx auch dann startet, wenn `matrix-synapse` (Docker-DNS) noch nicht verfuegbar ist
- Matrix-Inbetriebnahme lokal abgeschlossen: Synapse initialisiert (`/opt/fhir-server/matrix`), auf Postgres umgestellt und gestartet; Matrix-API sowie `/.well-known/matrix/*` ueber `https://fhir.woess.ch` verifiziert
- Nginx-Matrix-Upstream gehaertet: Docker-DNS mit `resolver 127.0.0.11` und variablem Upstream `matrix-synapse:8008` zur Laufzeitaufloesung
- TLS fuer Matrix aktiviert: Let's-Encrypt-Zertifikat fuer `matrix.woess.ch` via HTTP-01 Webroot ausgestellt; dedizierter Nginx-vHost (`matrix.woess.ch` auf 80/443) live aktiviert und erfolgreich validiert
- Matrix-Testseite bereitgestellt: statische HTML-Smoketest-Seite unter `/matrix-test/` mit Browser-Checks fuer `/_matrix/client/versions`, `/.well-known/matrix/*` und Federation-Key-Endpunkt
- Matrix-Testseite erweitert: Login-Testformular fuer `m.login.password` auf `/_matrix/client/v3/login` inkl. HTTP-Status und JSON-Response-Anzeige
- Matrix Import Bot umgesetzt: verarbeitet eMediplan-PDF/Bild und CDA-XML und antwortet im Raum mit Importstatus.
- Bot-Identitaetsgate gehaertet: unbekannte Absender und Abweichungen bei Patientenname oder Geburtsdatum werden vor dem Import blockiert.
- Bot-Testoberflaeche auf private Zwei-Personen-Raeume begrenzt; bestehende Raeume mit weiteren Mitgliedern werden nicht angeboten.
- Self-Service-Identitaetsverwaltung umgesetzt: authentifizierte `GET/PUT /matrix-bot-api/identity`-Aufrufe duerfen nur das Profil des per Matrix-Token verifizierten Benutzers lesen oder schreiben.

- eMediplan-Import stabilisiert: interner MedicationReference-Rewrite auf `fullUrl` korrigiert, wenn Upsert-Lookups Resource-IDs aendern
- eMediplan-QR/PDF-Import umgesetzt: PDF-Seiten werden gerendert, QR-Codes aus PDF/PNG/JPEG gelesen und in CHMED16A-Payloads ueberfuehrt.
- eMediplan-`PrscbBy`-Mapping umgesetzt: gueltige GLN erzeugt deterministischen CH-Core-Practitioner mit OID-System `urn:oid:2.51.1.3`; Freitext bleibt als `informationSource.display` erhalten.
- refdata.ch Partner-API angebunden: SOAP-Operation `Download`, Authentifizierung per `subscription-key`, client-seitige GLN-Filterung fuer die Stage-Umgebung und fail-safe Name-/Adressanreicherung.
- FHIR Query Client erweitert: fachliche Medikationszusammenfassung und Detailansicht zeigen den Verordner mit GLN beziehungsweise `GLN: nicht vorhanden`.
- EPIC-CDA Patient-Export erweitert: `recordTarget/patientRole` mit Identifier, Adresse, Telecom sowie erweiterten demografischen Feldern aus FHIR Patient
- EPIC-Medikations-Export erweitert: `effectiveTime/low`, `doseQuantity` und klinische Kommentar-Notizen aus FHIR MedicationStatement
- CDA-Import fuer Medikation erweitert: `originalText` und `translation` aus CDA-Code werden erhalten und in FHIR `medicationCodeableConcept.coding` uebernommen
- End-to-End validiert: `CDA-EPIC.xml` kann reimportiert werden und liefert im Export wieder strukturiertes Medication-Coding
- EPIC-Medikationslayout finalisiert: Export wieder im CDA-EPIC-List-Stil (`title=EPIC Medication Export`, `section/title=Medications`, `moodCode=EVN`)
- CH-EMED-nahe Produktanreicherung in eMediplan-Flow aktiv: optionale `Medication.form`, `Medication.ingredient`, `Medication.strength` aus Mapping
- API-Check clarified: Produktanreicherung sichtbar ueber Medication-Include (`_include=MedicationStatement:medication`), nicht direkt auf MedicationStatement

- Parser-Update fuer CDA-Immunization: Extraktion von `hl7:lotNumberText` und `manufacturerOrganization/hl7:name` aus `substanceAdministration`-Eintraegen
- CH-VACD-Dokumentpfad umgesetzt: `/cda/vacd/convert` erzeugt CH-VACD Immunization Administration Documents mit Bundle-/Composition-/Immunization-Profilen, UUID-Identifier, Composition-first und aufgelösten Referenzen
- CH-VACD-Filter umgesetzt: generische Abschnitte und unreferenzierte Ressourcen werden aus dem VACD-Dokument entfernt
- CH-VACD-Terminologie erweitert: bekannte Impfprodukte werden als CVX/SNOMED-CT/Swissmedic-Coding-Kette ausgegeben
- CH-VACD-Validierung abgesichert: vier fokussierte Regressionstests für Bundle-Struktur, Referenzen, Filterung und Metadaten
- Fehler behoben: `text_node` ist jetzt korrekt im Immunization-Parser definiert, sodass Dosage-Text und freier Text wieder zuverlaessig erfasst werden
- FHIR-Bundle-Import: bestehende Ressourcen werden nicht mehr nur mit `ifNoneExist` erstellt, sondern bei vorhandenem Identifier nach Lookup per `PUT ResourceType/{id}` aktualisiert
- Bundle-Dedupe korrigiert: mehrere gueltige `POST` auf denselben Ressourcentyp bleiben erhalten
- Procedure-Dedupe ergaenzt: Duplikate werden bereits im Mapper erkannt und nicht erst im finalen Bundle verworfen
- Encounter-Doppelpfad entfernt: Section-Code `46240-8` mappt nicht mehr auf den Encounter-Mapper
- Clinical Notes werden aus narrativen CDA-Sections extrahiert und als `DocumentReference` mit referenzierten `Binary`-Ressourcen in das Bundle aufgenommen
- Patient-Import erweitert: `maritalStatus`, `deceasedBoolean`, `communication`, `contact`, `patient-birthPlace`, `patient-religion` und Contact-Identifier aus CDA werden in CH-Core-Patient uebernommen
- `participant/associatedEntity` aus CDA-MWO wird als `Patient.contact` mit CH-Core-`contactData` plus fachlicher Beziehung (`SPS`) abgebildet
- EchoSOS-QR/PKPass-Import umgesetzt: Patient-Upsert nach Name/Geburtsdatum, QR-Blutgruppe und Notfallkontakt sowie anschliessende `Patient/{id}/$everything?_count=500`-Abfrage
- EchoSOS-Kontaktmodell erweitert: `Patient.contact` und `RelatedPerson` werden gemeinsam angezeigt; `ECON` kennzeichnet Notfallkontakte, PCP wird ueber `CareTeam.participant` und `Practitioner` referenziert
- CareTeam-Reimport abgesichert: Vorhandene PCP-Teilnehmer bleiben bei CDA-Updates erhalten, wenn der neue CDA-Abschnitt keinen PCP liefert
- EchoSOS-Observations klassifiziert: Labor mit `laboratory`, Vitalzeichen mit `vital-signs`, Sozialanamnese mit `social-history`; unklassifizierte Observations und Encounter werden nur in der Notfallansicht ausgeblendet
- EchoSOS-Blutgruppe standardisiert: LOINC `882-1` fuer kombinierte ABO/Rh-Werte; ABO `883-9` und Rh `10331-7` werden in der Anzeige kombiniert
- Schwangerschaftsstatus als Observation mit LOINC `82810-3` und SNOMED CT `77386006` abgebildet
- CDA-Autoren dokumentbezogen aufgeloest: ID-only-Authoren werden, wenn im selben CDA benannt, auf den vorhandenen Namen zurueckgefuehrt
- HAPI-Testbestand gezielt bereinigt: doppelte Patient-, Practitioner-, PractitionerRole-, Organization-, Observation- und CareTeam-Datensaetze entfernt
- Builder-Dedupe erweitert: redundante `name`, `telecom` und `address` werden fuer Patient und Practitioner vor dem Persistieren reduziert
- Infrastruktur stabilisiert: `fhir-server` und `fhir-middleware` verwenden dasselbe externe Docker-Netzwerk `fhir-server_fhir-net`
- verifiziert: Re-Imports bleiben fuer Referenzressourcen und deduplizierte Bundle-Eintraege idempotent

### Phase 3

- US Core Unterstützung

### Phase 4

- FHIR → CDA
- FHIR → HL7v2

### Phase 5

- Kafka Integration
- RabbitMQ Integration
- Microservice Aufteilung

---

## Entscheidungen

### ADR-001

BridgeLink orchestriert.
Middleware transformiert.

Status: Accepted

### ADR-002

HAPI FHIR ist Source of Truth.

Status: Accepted

### ADR-003

Parser, Domain, Mapper und Builder bleiben getrennte Schichten.

Status: Accepted

### ADR-004

FHIR Bundles werden an BridgeLink zurückgegeben.

Status: Accepted

### ADR-005

Clinical Notes werden über DocumentReference und DiagnosticReport umgesetzt.

Status: Proposed

---

## Aktueller Fokus

Status: Active Development

Aktuelles Epic:
US Core Clinical Notes

Aktuelle Aufgabe:
Analyse und Implementierung von:

- DocumentReference
- Binary
- DiagnosticReport

Nächstes Ziel:
Clinical Notes aus CDA Sections extrahieren und als FHIR-Ressourcen bereitstellen.

---

## Technical Debt

### Offen

- HL7v2 Parsing bisher nur Patient
- Keine Kafka Integration
- Keine RabbitMQ Integration
- Keine Provenance Ressourcen
- Keine Composition Ressourcen
- Keine Subscription Unterstützung

### Zu prüfen

- Vollständige US Core Kompatibilität
- Bulk Import Strategie
- Performance bei großen CDA Dokumenten
- CH eTOC Document-Konformitaet: fuer ein echtes CH-eTOC-Dokument ist ein `Bundle.type=document` mit `Composition` als erstem Entry erforderlich; aktueller UMZH-Pfad liefert bewusst ein Workflow-`Bundle.type=collection`
- CH eTOC Observation-Profile fuer diagnostische Ergebnisse (Lab/Pathology/Radiology/Cardiology) gezielt auf bestehende Observation-Mappings abbilden
- CH eTOC Observation-Profile fuer diagnostische Ergebnisse (Lab/Pathology/Radiology/Cardiology): initiale Heuristik aktiv; Feintuning gegen reale CDA-Stichproben und IG-Beispiele offen

---

## Letzte Session

Datum: 2026-07-23

Erarbeitet:

- Projekt-Memory erstellt
- Zielarchitektur dokumentiert
- HAPI PostgreSQL geprüft
- hfj_resource Tabelle festgestellt: 0 Ressourcen
- Vorbereitung US Core Clinical Notes

Nächster Schritt:

- Analyse bestehender CDA Sections
- Implementiertes Clinical Note Domain Model
- Implementierung DocumentReference Builder

---

## Dokument

Version: 1.1
Letzte Aktualisierung: 2026-07-28
Verantwortlich: Markus Wöss

## Laufzeitumgebung

### Docker Container

- fhir-middleware
- fhir-server (HAPI FHIR)
- fhir-postgres (PostgreSQL 16)
- fhir-adminer
- fhir-nginx

### Aktuelle Erkenntnisse

- HAPI FHIR nutzt PostgreSQL
- Tabelle hfj_resource wurde geprüft
- Aktueller Bestand: 0 Ressourcen

## Backlog - Nächste Schritte

### Clinical Notes

Status: In Planung

Tasks:

- [x] Clinical Note Domain Model erstellen
- [x] DocumentReference Builder erstellen
- [x] Binary Strategie definieren
- [x] CDA Narrative Mapping definieren
- [x] DiagnosticReport Mapping definieren (UMZH Referral Bundle, initiale Version)
- [ ] US Core Clinical Notes Tests erstellen

---

## BridgeLink - Analyse CH UMZH Connect IG

Stand: 2026-07-28

### Ziel

Bewertung der bestehenden BridgeLink-Architektur gegenueber dem HL7 Switzerland Implementation Guide CH UMZH Connect (R4) und Identifikation der notwendigen Erweiterungen fuer die Unterstuetzung von Referral- und Clinical-Order-Workflows.

### Ueberblick CH UMZH Connect

Das CH UMZH Connect IG definiert einen standardisierten FHIR-basierten Austauschprozess fuer:

- Ueberweisungen (Referrals)
- Externe Leistungsauftraege
- Verlegungen
- Interinstitutionelle klinische Kommunikation

Der Schwerpunkt liegt auf einem API-basierten Clinical-Order-Workflow zwischen einem Auftraggeber (Placer) und einem Auftragsempfaenger (Fulfiller).

### Zentrales Workflow-Modell

Das IG basiert auf dem HL7 Clinical Order Workflow (COW).

Grundprinzip:

```text
Placer
  |
  | erstellt ServiceRequest
  | erstellt Task
  v
Fulfiller

Task.basedOn -> ServiceRequest
```

Der Fulfiller uebernimmt die Verwaltung des Task-Lifecycles und informiert den Placer ueber Statusaenderungen und Ergebnisse.

Typische Task-Status:

```text
requested
accepted
in-progress
completed
cancelled
```

### Erwartete FHIR-Ressourcen

Workflow:

- ServiceRequest
- Task

Administrative Daten:

- Patient
- Practitioner
- PractitionerRole
- Organization
- Coverage

Klinische Daten:

- Condition
- MedicationStatement
- AllergyIntolerance
- Observation
- Procedure

Dokumente:

- DocumentReference
- Binary

Weitere Ressourcen:

- ImagingStudy
- Appointment
- DiagnosticReport

### BridgeLink Ist-Zustand

Bereits vorhanden

Administrative Ressourcen:

- Patient
- Practitioner
- PractitionerRole
- Organization
- Encounter

Klinische Ressourcen:

- Condition
- Observation
- Medication
- Allergy
- Procedure
- CareTeam
- Goal
- Immunization
- Consent

Dokumentenmodell:

- Clinical Note Domain Model
- DocumentReference Builder
- Binary Builder

Infrastruktur:

- CDA Parsing
- FHIR Bundle Builder
- HAPI FHIR Integration
- Idempotenter Import
- Referenzaufloesung

### Mapping BridgeLink -> UMZH Connect

Vollstaendig oder weitgehend abgedeckt

Patient

BridgeLink:

```text
Patient Domain
CH Core Patient Builder
```

Status: Vorhanden

Practitioner

BridgeLink:

```text
Practitioner Domain
CH Core Practitioner Builder
PractitionerRole Builder
```

Status: Vorhanden

Organization

BridgeLink:

```text
Organization Domain
CH Core Organization Builder
```

Status: Vorhanden

Condition

BridgeLink:

```text
Condition Mapper
```

Status: Vorhanden

Medication

BridgeLink:

```text
Medication Mapper
```

Status: Vorhanden

AllergyIntolerance

BridgeLink:

```text
Allergy Mapper
```

Status: Vorhanden

Observation

BridgeLink:

```text
Observation Builder
```

Status: Vorhanden

DocumentReference

BridgeLink:

```text
Clinical Note Extraction
DocumentReference Builder
```

Status: Vorhanden

Binary

BridgeLink:

```text
Binary Builder
```

Status: Vorhanden

### Identifizierte Luecken

1. ServiceRequest

Groesste fachliche Luecke.

Im UMZH-Modell repraesentiert der ServiceRequest:

- Ueberweisung
- Auftrag
- Klinische Fragestellung
- Gewuenschte Leistung

BridgeLink besitzt derzeit kein eigenes ServiceRequest-Domainmodell.

Empfehlung: Neues Domain Model

```python
class ServiceRequestDomain:
  identifier: str
  status: str
  intent: str

  patient_id: str

  requester: str
  recipient: str

  category: list[str]

  code: str

  reason_codes: list[str]
  supporting_info: list[str]
```

Status: Fehlt

2. Task

Im UMZH-Workflow steuert der Task den gesamten Prozess.

Aufbau:

```text
Task
 └── basedOn -> ServiceRequest
```

BridgeLink besitzt bereits Workflow-Stages:

```text
initial
updated
completed
```

Diese lassen sich direkt auf Task-Status abbilden.

Mapping-Vorschlag:

```text
initial
  -> requested

updated
  -> in-progress

completed
  -> completed
```

Status: Fehlt

3. DiagnosticReport

DiagnosticReport befindet sich bereits auf der Project Roadmap.

Besonders relevant fuer:

- Laborberichte
- Radiologie
- Tumorboard
- Pathologie

Empfohlene Struktur:

```text
DiagnosticReport
 ├─ code
 ├─ conclusion
 ├─ result
 └─ presentedForm
```

Status: Offen

### Empfohlene Erweiterung der Domain-Architektur

Aktuell:

```text
Patient
Practitioner
Organization
Encounter
ClinicalNote
```

Ziel:

```text
Patient
Practitioner
Organization
Encounter
ClinicalNote

ServiceRequest
Task
```

### Empfohlene neue Builder

ServiceRequest Builder

Datei:

```text
app/builders/servicerequest_builder.py
```

Verantwortlich fuer:

- Referral-Auftraege
- Clinical Questions
- Service Orders

Task Builder

Datei:

```text
app/builders/task_builder.py
```

Verantwortlich fuer:

- Workflow-Lifecycle
- Statusverwaltung
- Referenzierung des ServiceRequest

### Zielbild UMZH Referral Bundle

Heute:

```text
Patient
Practitioner
Organization

Condition
Observation

DocumentReference
Binary
```

Ziel:

```text
Patient
Practitioner
Organization

ServiceRequest
Task

Condition
MedicationStatement
AllergyIntolerance

Observation
Procedure

DocumentReference
Binary

DiagnosticReport
```

Dieses Bundle entspricht weitgehend dem fachlichen Kernmodell des CH UMZH Connect IG.

### Empfohlene Roadmap-Erweiterung

Clinical Notes Epic abschliessen

Offene Arbeit:

```text
DiagnosticReport Mapping
```

Neues Epic: UMZH Referral Workflow

Umfang:

- ServiceRequest Domain Model
- ServiceRequest Builder
- Task Builder
- Referral Bundle Assembler
- CH UMZH Connect Profilunterstuetzung
- Fulfiller/Placer Workflow-Unterstuetzung
- End-to-End Tests

### Strategische Bewertung

BridgeLink ist bereits deutlich mehr als ein einfacher CDA-Konverter.

Der aktuelle Funktionsumfang deckt bereits den groessten Teil der klinischen Inhalte des CH UMZH Connect IG ab.

Die wesentlichen fehlenden Bausteine sind:

1. ServiceRequest
2. Task
3. DiagnosticReport

Nach Umsetzung dieser Komponenten kann BridgeLink als vollstaendige Referral- und Clinical-Order-Workflow-Plattform auf Basis des CH UMZH Connect Standards positioniert werden.

Dadurch entwickelt sich BridgeLink von:

```text
CDA -> FHIR Converter
```

zu:

```text
FHIR Clinical Order and Referral Integration Platform
```

fuer Placer- und Fulfiller-Szenarien innerhalb des UMZH-Connect-Oekosystems.
