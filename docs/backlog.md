# Backlog

Stand: 2026-09-10

## Aktueller Stand

Die Middleware deckt den produktiven CDA-zu-FHIR-Pfad, CH-VACD sowie eMediplan-
Import aus Text, PDF und Bild ab. GLN-Verordner werden als CH-Core-Practitioner
mit optionaler refdata.ch-Anreicherung abgebildet. Der Matrix-Bot importiert
eMediplan- und CDA-Dokumente nur nach erfolgreicher Absender-Patienten-Pruefung.
Der Backlog konzentriert sich auf offene Clinical-Note-Erweiterungen,
UMZH-Sendemodell, API-Struktur, Terminologiepflege und Testabdeckung.

## CH VACD Immunization Administration

- [x] `/cda/vacd/convert` als `Bundle.type=document` umgesetzt
- [x] CH-VACD Bundle-, Composition- und Immunization-Profile gesetzt
- [x] Composition als erstes Bundle-Entry und UUID-Identifier umgesetzt
- [x] Bundle-Referenzen auf `fullUrl` normalisiert
- [x] generische, nicht referenzierte CDA-Ressourcen aus dem VACD-Pfad entfernt
- [x] Impf-Codings für bekannte Produkte als CVX/SNOMED CT/Swissmedic ausgegeben
- [x] VACD-Regressionstests für Profilierung, Filterung und Referenzauflösung ergänzt
- [ ] CH-VACD-Package im produktiven Validator standardmäßig laden
- [ ] zusätzliche Swissmedic-Produktmappings für FSME und weitere Impfstoffe fachlich verifizieren

Neu seit 2026-07-30:

- EPIC-CDA Medikation End-to-End stabilisiert (`cda/import` -> FHIR -> `fhir/medications/epic-cda/from-server?patient_id=<id>&count=100`).
- MedicationReference-Rewrite fuer eMediplan-Import bei Upsert-ID-Wechsel korrigiert.
- `recordTarget` im EPIC-CDA mit erweiterten Patientendaten ergänzt.
- EPIC-Medikations-Export wieder auf CDA-EPIC-kompatibles List-Layout zurueckgestellt (`title=EPIC Medication Export`, `section/title=Medications`, `moodCode=EVN`).
- CH-EMED-nahes Medication-Enrichment eingebaut (Profil-Meta + optionale Felder `form`, `ingredient`, `strength` aus Mapping).
- Clarification: Compendium-/Produktanreicherung liegt in `Medication`, nicht in `MedicationStatement`.
- eMediplan-QR aus PDF/Bild fuer Convert und Import umgesetzt.
- `PrscbBy` als gueltige GLN geprueft und mit OID `urn:oid:2.51.1.3` als CH-Core-Practitioner abgebildet; Freitext bleibt `informationSource.display`.
- refdata.ch Partner-API fuer optionale Name-/Adressanreicherung von GLN-Practitionern angebunden.
- Matrix-Bot fuer eMediplan und CDA mit blockierender Identitaetspruefung, privaten Zwei-Personen-Raeumen und Self-Service-Profilpflege umgesetzt.

## UMZH Connect

- [x] `/cda/umzh/convert` mit Stages `initial|updated|completed`
- [x] `target=sandbox-placer` für sandbox-kompatible absolute Referenzen
- [x] `/cda/umzh/send` für Convert+Versand an externes FHIR-Ziel mit Versandreport
- [x] Unit-Tests für Convert-Stages und Send-Service
- [ ] Outbound-Authorization nicht nur als Query, sondern zusätzlich als Header-Eingang standardisieren
- [ ] Optionaler Batch-/Transaction-Versandmodus für Zielsysteme ergänzen, die kein einzelnes `PUT ResourceType/{id}` bevorzugen

## Clinical Notes

Status: In Umsetzung

- [x] Clinical Note Domain Model erstellt
- [x] Clinical-Note-Extraktion aus CDA-Sections umgesetzt
- [x] `DocumentReference`-Builder umgesetzt
- [x] `Binary`-Abbildung fuer Anhaenge umgesetzt
- [x] Narrative und Attachment-Tests fuer Clinical Notes erstellt
- [ ] DiagnosticReport als zusaetzliche oder alternative Abbildung fachlich festlegen
- [ ] DiagnosticReport-Mapping nur dort einfuehren, wo echte Befundlogik vorliegt

## Bundle und Import

- [x] Bundle-Dedupe fuer unterschiedliche `POST`-Eintraege korrigiert
- [x] Einzelressourcen vor dem Import automatisch als Transaction-Bundle verpackt
- [x] Dokumentbundles vor dem Import in Transaction-Bundles ueberfuehrt
- [x] Fehlende Transaction-Requests anhand von Ressourcentyp und ID ergaenzt
- [x] Referenzressourcen-Update per Lookup und `PUT ResourceType/{id}` umgesetzt
- [x] Deterministischer Upsert fuer Organization und Practitioner umgesetzt
- [x] Bestehende Test-Dubletten in HAPI gezielt bereinigt
- [x] MedicationReference-Rewrite bei geaenderter Medication-ID (Upsert) abgesichert
- [x] CH-Core-Practitioner aus gueltiger eMediplan-`PrscbBy`-GLN mit OID-System und refdata-Anreicherung abgesichert
- [ ] Importverhalten fuer weitere Ressourcentypen explizit testen
- [ ] Fehlerbilder aus HAPI-Antworten einheitlicher auf API-Fehler abbilden
- [x] EchoSOS-QR-Import mit anschliessender Patient-`$everything`-Abfrage umgesetzt
- [x] Bestehende CareTeam-PCP-Teilnehmer bei CDA-Reimport erhalten
- [ ] TX-Validierung fuer Pharmacode-NamingSystem ueber eine passende Schweizer Terminologiequelle ergaenzen

## EPIC Medication Reconciliation

- [x] `effectiveDateTime` -> CDA `effectiveTime/low`
- [x] FHIR `doseAndRate.doseQuantity` -> CDA `doseQuantity`
- [x] Klinisch nutzbare Notizen als CDA `entryRelationship` Kommentar
- [x] CDA `translation`-Codes beim Import erhalten und im Export wiederverwenden
- [x] Verordner in der fachlichen Medikationszusammenfassung mit GLN-Status anzeigen
- [ ] Route/Frequency noch strukturierter exportieren, falls im FHIR-Bestand vorhanden
- [ ] Optionalen Fallback fuer `nullFlavor=UNK` + `originalText` im Export evaluieren

## API und Struktur

- [ ] `app/main.py` in Router und schlankere Service-Grenzen zerlegen
- [ ] Legacy-/Debug-Code in `main.py` reduzieren oder kapseln
- [ ] Endpunkt-Dokumentation fuer Dateiupload, `raw_xml` und Raw-Body vereinheitlichen

## Testabdeckung

- [x] Tests fuer Bundle-Dedupe vorhanden
- [x] Tests fuer Clinical Notes vorhanden
- [x] Tests fuer Referenzressourcen-Services vorhanden
- [x] Regressionstests fuer Patient- und Practitioner-Dedupe vorhanden
- [ ] End-to-End-Tests fuer `/cda/convert` und `/cda/import` mit realistischen CDA-Beispielen erweitern
- [x] Regressionstests fuer `/cda/vacd/convert` mit CH-VACD-Dokumentstruktur ergänzt
- [x] Regressionstest fuer CH-Core-Practitioner mit GLN-OID aus eMediplan ergaenzt
- [ ] Zusaetzliche Profilvarianten fuer Mappings absichern

## Spaeter

- [ ] US-Core-Ausrichtung priorisieren, sobald fachlich benoetigt
- [ ] HL7v2-Pfad produktiv vervollstaendigen oder klar abgrenzen
