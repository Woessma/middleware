# Backlog

Stand: 2026-11-05

## Medikation und Validierung: aktueller Abschluss

- [x] Interner Husky-Dienst fuer CDA sowie separate PMLC-/VACD-Profilpruefung
- [x] PMLC-Vorschau aus aktiven HAPI-Statements mit lokaler Keycloak-Pruefung
- [x] Import- und EPR-Ausgabemapping getrennt korrigiert, Altbestand unveraendert
- [x] Verpflichtendes finales Medikations-Importgate in der Middleware deployt
- [x] Erfundene Swissmedic-Codes und pauschale COVID-Marken-/CVX-Zuordnung entfernt
- [x] Fehler-/Warnungsanzeige mit expliziter Profilangabe oder gekennzeichnetem Kontext
- [ ] CDA-BridgeLink-Route auf `/cda/prepare` aktivieren: Templates/Channel speichern,
      redeployen und Gate einschliesslich Fehlerfall Ende-zu-Ende pruefen
- [ ] Original-CDA nach Impfcodekorrektur erneut in der Werkbank pruefen
- [ ] PMLC-PDF/A und QR sowie fehlende medizinische Pflichtangaben ergaenzen,
      bevor eine profilkonforme EPR-Ausgabe freigegeben wird
- [ ] Passende CDA-Erweiterungsschemas/Schematrons fuer die untersuchten
      EPIC-/AT-Templateversionen installieren; Basis-XSD ist keine Profilfreigabe

## Aktueller Stand

Die Middleware deckt den produktiven CDA-zu-FHIR-Pfad, CH-VACD sowie eMediplan-
Import aus Text, PDF und Bild ab. GLN-Verordner werden als CH-Core-Practitioner
mit optionaler refdata.ch-Anreicherung abgebildet. Der Matrix-Bot importiert
eMediplan- und CDA-Dokumente nur nach erfolgreicher Absender-Patienten-Pruefung.
Der Backlog konzentriert sich auf offene Clinical-Note-Erweiterungen,
UMZH-Sendemodell, API-Struktur, Terminologiepflege und Testabdeckung.

## Reader, Refdata und Neuaufbau

- [x] eRezept & eMediplan Reader mit lokalen PDF-/Bildvorschauen,
      getrennten QR-/Metadaten-Ergebnissen und Original-/FHIR-JSON-Download
- [x] Reader umbenannt; `/erezept-reader.html` und `/qr-reader.html` bleiben Aliase
- [x] Migrationskonzept und Katalog mit 32 priorisierten offenen Fragen als
      lokale PDF-Unterlagen erstellt (nicht im Repository versioniert)
- [ ] Neuaufbauumfang, direkte OIE-Pilotauswahl, MPI und Verantwortlichkeiten entscheiden
- [ ] DB-Administrator stellt `omnilink_refdata` und getrennte Importer-/Leserrollen bereit;
      aktuelle CloudBeaver-FHIR-Rolle hat keine Datenbank-Erstellungsrechte
- [ ] Refdata-XML-Datenmodell und Streaming-Import mit GLN-Index, Datenstand,
      validierter atomarer Aktualisierung und Rueckfall auf vorherigen Bestand umsetzen
- [ ] Lokalen Refdata-Lookup in die Middleware integrieren; Registerstatus und
      Berechtigung nicht mit einer gueltigen GLN-Pruefziffer gleichsetzen
- [ ] Aktualisierung, kontrollierte externe Abfragen, Fehler-/Veraltungsregeln
      sowie Backup/Restore festlegen und testen
- [ ] Infrastruktur und Referenzdaten-Aktualisierung in der zustaendigen
      Ansible-Quelle umsetzen; bisher keine Ansible-Aenderung erfolgt
- [ ] Demo-Abnahme, Rollback, Kosten/Termine und Produktions-RPO/RTO vereinbaren

## CH VACD Immunization Administration

- [x] `/cda/vacd/convert` als `Bundle.type=document` umgesetzt
- [x] CH-VACD Bundle-, Composition- und Immunization-Profile gesetzt
- [x] Composition als erstes Bundle-Entry und UUID-Identifier umgesetzt
- [x] Bundle-Referenzen auf `fullUrl` normalisiert
- [x] generische, nicht referenzierte CDA-Ressourcen aus dem VACD-Pfad entfernt
- [x] Quell-Impf-Codings erhalten; keine kuenstlichen Swissmedic-Produktcodes erzeugen
- [x] VACD-Regressionstests für Profilierung, Filterung und Referenzauflösung ergänzt
- [x] CH-VACD 6.0.0 im internen HAPI vorhanden und im Husky-Dienst lokal gebuendelt
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
- Beratende CH-EMED-Validierung `POST /emediplan/validate` (2026-11-06): prueft das konvertierte Bundle intern mit HAPI gegen deklarierte Profile plus striktes `ch-emed-medicationstatement` 6.0.0 auf einer Kopie; Convert-/Importwege und deren blockierende Pruefung bleiben unveraendert. Eingaben wie Convert inkl. PDF/Bild mit eMediplan-QR; eigene Werkbank-Use-Cases fuer Text und QR-Datei.

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
- [x] EchoSOS-QR/PKPass-Auswahlen fuer Allergien samt Reaktionen und Vorgeschichte dekodieren und als `AllergyIntolerance`/`Condition` persistieren
- [x] EchoSOS-Blutgruppe als LOINC-Observation und bis zu drei Notfallkontakte in `Patient.contact` persistieren
- [x] Explizite EchoSOS-Organspende-Zustimmung/Ablehnung als `Consent` persistieren; fehlender Schweizer Registereintrag ist keine Ablehnung
- [ ] EchoSOS-Medikamentenauswahlen und Freitext in geeignete FHIR-Ressourcen ueberfuehren
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

- [ ] Social-History-Mapper: `DUPLICATE OBSERVATION IDENTIFIER` beheben — das
      EPIC-CDA erzeugt drei Observations mit identischem Identifier-Hash
      (`cda-import-social-history`); vermutlich fehlt ein unterscheidendes
      Merkmal (Code/Zeilenindex) im Hash. Beobachtet am 2026-10-30 im Live-Log.
- [ ] CDA-Convert Option C: Conditional Update per Identifier im Bundle
      (`PUT Patient?identifier=...`) statt lokal vergebener UUIDs — eliminiert
      den Edge Case, dass mehrfaches Konvertieren eines neuen Patienten vor dem
      ersten Import unterschiedliche IDs erzeugt.
- [ ] BridgeLink Destination 99: Writer-Logging aufraeumen (loggt
      `responseStatusCode=null`, da es vor dem Response Transformer laeuft).
- [ ] US-Core-Ausrichtung priorisieren, sobald fachlich benoetigt
- [ ] HL7v2-Pfad produktiv vervollstaendigen oder klar abgrenzen
