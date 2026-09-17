# Architektur

Stand: 2026-09-10

## Zielarchitektur

Quellsystem
→ BridgeLink
→ Python Middleware
→ HAPI FHIR Lookup
→ BridgeLink
→ HAPI FHIR Import

Zusatzpfad fuer EPIC Medikation:

EPIC CDA
→ `/cda/import`
→ FHIR MedicationStatement/Medication in HAPI
→ `/fhir/medications/epic-cda/from-server?patient_id=<id>&count=100`
→ EPIC CDA Export

## Komponenten

- BridgeLink: Orchestrierung, Routing, Monitoring, Auftragssteuerung
- Python Middleware: Parsing, Transformation, Mapping, Bundle-Erzeugung
- HAPI FHIR: FHIR Repository, Source of Truth, Ressourcenverwaltung
- refdata.ch Partner-API: optionale Validierung und Anreicherung von GLN-Daten
- Matrix Import Bot: geschuetzter Dateiimport fuer eMediplan und CDA

## Software-Architektur

- Parser
- Domain Layer
- Mapper
- Builder
- FHIR Bundle
- EPIC-CDA Export Layer (FHIR -> CDA)

## Schnittstellen

- CDA-API: `/cda/debug`, `/cda/convert`, `/cda/import`, `/cda/umzh/convert`, `/cda/umzh/send`
- CH-VACD-API: `/cda/vacd/convert` fuer CH-VACD Immunization Administration Documents
- eMediplan-API: `/emediplan/convert`, `/emediplan/import`, `/emediplan/import-bundle`, `/emediplan/qr/convert`, `/emediplan/qr/import`, `/emediplan/epic-cda`
- EPIC-CDA-API: `/fhir/medications/epic-cda`, `/fhir/medications/epic-cda/from-server` (Default `count=100`)
- Medication-Lookup fuer angereicherte Produktdaten: `_include=MedicationStatement:medication`
- UMZH Convert: `workflow_stage=initial|updated|completed`, optional `target=default|sandbox-placer`
- UMZH Send: Convert + Versandreport mit `destination_base_url` (und optionalem Outbound-Authorization-Header)
- CH VACD Convert: `Bundle.type=document`, Composition zuerst, CH-VACD Bundle-/Composition-/Immunization-Profile, UUID-Identifier und aufgelöste `fullUrl`-Referenzen
- FHIR-Import: Einzelressourcen und Dokumentbundles werden vor dem Versand als Transaction-Bundle stabilisiert; fehlende Requests werden aus Ressourcentyp und ID abgeleitet
- EchoSOS-Import: QR/PKPass -> Patient-Upsert -> Blutgruppen-Observation -> `$everything`-Abfrage -> Notfallansicht
- Kontaktmodell: `Patient.contact` plus `RelatedPerson`; PCP über `CareTeam.participant` und `Practitioner`-Referenz
- EchoSOS-Ansicht gruppiert Observations nach `vital-signs`, `laboratory` und `social-history`; unklassifizierte Observations und Encounter werden ausgeblendet
- HAPI FHIR: HTTP-API über `http://fhir-server:8080/fhir`

## eMediplan-Verordner und GLN

`Medicaments[].PrscbBy` enthaelt nach CHMED16A entweder die GLN oder die
Bezeichnung der verordnenden Person. Eine gueltige GLN wird mit dem
GS1-Modulo-10-Verfahren geprueft und als CH-Core-`Practitioner` mit dem
Identifier-System `urn:oid:2.51.1.3` abgebildet. Die optionale refdata.ch
Partner-API ergaenzt Name und Adresse. Ist `PrscbBy` keine GLN, bleibt der Wert
als `MedicationStatement.informationSource.display` erhalten. Das separate
Top-Level-Feld `Auth` bezeichnet den Dokumentautor und wird nicht als
Verordner-GLN interpretiert.

## Matrix Import Bot

Der Bot verarbeitet eMediplan-PDFs und -Bilder sowie CDA-XML. Vor dem Import
muessen Name und Geburtsdatum des Patienten zum hinterlegten Profil des
Matrix-Absenders passen; unbekannte oder abweichende Absender werden blockiert.
Die Testoberflaeche erstellt und verwendet ausschliesslich private Raeume mit
genau dem Benutzer und dem Bot. Profile koennen ueber die authentifizierte
Self-Service-API `GET/PUT /api/identity` gepflegt werden.

## Deployment

- Docker Compose Service `middleware`
- Externes Netzwerk `fhir-server_fhir-net`
- Interner Port `8000`
- Externer Zugriff über Nginx-Proxy: `/middleware/*`

## CH VACD

Der Endpoint `POST /cda/vacd/convert` konvertiert CDA-Impfdaten in ein CH-VACD-Immunization-Administration-Dokument nach CH VACD 1.0.0. Für den openEHR-basierten Versand gilt die offizielle Dokumentdefinition unter https://fhir.ch/ig/ch-vacd/1.0.0/immunization-administration-document.html.

Der Pfad filtert generische CDA-Inhalte auf CH-VACD-relevante Abschnitte und Ressourcen. Impfungen werden in der Composition-Section `11369-6` referenziert. Für bekannte Produkte werden alternative Codings in `Immunization.vaccineCode.coding` ausgegeben: CVX, SNOMED CT und Swissmedic.

Offizielle Profile:

- Bundle: `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration`
- Composition: `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-composition-immunization-administration`
- Immunization: `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization`

## Import-Stabilisierung

Vor dem FHIR-Import wird der Payload vereinheitlicht. Einzelne Ressourcen werden
als Transaction-Bundle verpackt. Bei Dokumentbundles wird der Bundle-Typ für den
Import von `document` auf `transaction` geändert; Composition und übrige
Ressourcen bleiben erhalten. Für Entries ohne Request werden vorhandene
Ressourcen-IDs mit `PUT ResourceType/{id}` und neue Ressourcen mit
`POST ResourceType` importiert. Fachlich doppelte Entries werden vor dem Versand
entfernt.
