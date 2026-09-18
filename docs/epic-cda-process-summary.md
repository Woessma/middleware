# EPIC CDA Process Summary

Stand: 2026-09-04

Dieses Dokument beschreibt den aktuellen End-to-End Prozess fuer:
- CDA Import nach FHIR
- FHIR Mapping fuer Medikation
- EPIC CDA Export aus FHIR als medikationsfokussierte Ableitung von app/tests/data/CDA-EPIC.xml

Referenz-Testpfad:

`app/tests/data/CDA-EPIC.xml` -> `POST /middleware/cda/import` via BridgeLink -> `GET /middleware/fhir/medications/epic-cda/from-server?patient_id=<id>&count=100` via BridgeLink

Aktuelle Bruno-Basisadresse:

```text
http://192.168.167.212:9080
```

Damit lautet der Import-Aufruf vollständig:

```text
POST http://192.168.167.212:9080/middleware/cda/import
```

Die Referenzen nutzen die Kommentar-IDs in den Python-Dateien.

## 1) CDA Import: Code und Text extrahieren

- PROC-CDA-01 in app/parser/cda/section_parser.py:
  - Loest originalText-Referenzen auf, wenn ein Code nullFlavor/UNK hat.
  - Ziel: Medikamentenname geht nicht verloren.

- PROC-CDA-02 in app/parser/cda/section_parser.py:
  - Liest translation-Codes (z. B. SNOMED) aus dem CDA.
  - Ziel: Strukturierte Codes bleiben fuer das FHIR Mapping erhalten.

## 2) FHIR Mapping: MedicationStatement und Medication aufbauen

- PROC-MAP-01 in app/mappers/medication_mapper.py:
  - Uebernimmt translation-Codes in medicationCodeableConcept.coding.
  - Ziel: Auch bei fehlendem Primaercode bleibt strukturiertes Coding erhalten.

- PROC-MAP-02 in app/mappers/medication_mapper.py:
  - Uebernimmt doseQuantity nach dosage.doseAndRate.
  - Ziel: Quantitative Dosis ist fuer den Export strukturiert verfuegbar.

- eMediplan-Medication-Enrichment in app/services/emediplan_service.py und app/terminology/emediplan_medication_map.py:
  - Normalisiert Produktidentitaet (GTIN/Pharmacode/ProductNumber).
  - Schreibt optionale CH-EMED-nahe Felder auf `Medication` (`form`, `ingredient`, `strength`), falls im Mapping vorhanden.
  - Prueft `PrscbBy` als GLN mit GS1 Modulo 10.
  - Erzeugt bei gueltiger GLN einen CH-Core-`Practitioner` mit dem Identifier-System `urn:oid:2.51.1.3`.
  - Reichert den Practitioner optional ueber die refdata.ch Partner-API mit Name und Adresse an.
  - Bewahrt nicht als GLN erkennbare Werte als `MedicationStatement.informationSource.display` auf.

`PrscbBy` enthaelt laut CHMED16A entweder GLN oder Bezeichnung des Verordners.
Das Top-Level-Feld `Auth` bezeichnet dagegen den Dokumentautor; beide Werte
werden nicht automatisch zusammengefuehrt.

## 3) EPIC CDA Export aus FHIR

- PROC-EXP-01 in app/services/emediplan_service.py:
  - effectiveDateTime wird als Fallback fuer effectivePeriod/start genutzt.

- PROC-EXP-02 in app/services/emediplan_service.py:
  - Fallback auf Medication.identifier fuer code/codeSystem, wenn kein Coding vorliegt.

- PROC-EXP-03 in app/services/emediplan_service.py:
  - Filtert technische Note-Inhalte (z. B. Status/Timestamp) und behaelt klinisch nutzbare Texte.

- PROC-EXP-04 in app/services/emediplan_service.py:
  - Schreibt effectiveTime (low/high) in substanceAdministration.

- PROC-EXP-05 in app/services/emediplan_service.py:
  - Schreibt doseQuantity in substanceAdministration.

- PROC-EXP-06 in app/services/emediplan_service.py:
  - Schreibt klinische Notizen als entryRelationship/act Kommentar.

## 3.1) Sichtbarkeit von Compendium-Daten

- `MedicationStatement` enthaelt Therapiekontext (Reason, Dosage, Effective Period), aber nicht die angereicherte Produktstruktur.
- Angereicherte Produktdaten liegen in `Medication`.
- Fuer API-Checks deshalb mit Include arbeiten:
  - `GET /fhir/MedicationStatement?subject=Patient/<id>&_include=MedicationStatement:medication&_include=MedicationStatement:subject&_count=100`

## 3.2) Sichtbarkeit des Verordners

Der FHIR Query Client zeigt `MedicationStatement.informationSource` in der
fachlichen Medikationszusammenfassung als **Verordner**. Ist der referenzierte
Practitioner im Bundle enthalten, werden Name und GLN dargestellt. Bei einem
reinen Freitextwert wird `(GLN: nicht vorhanden)` ausgewiesen.

## 4) Ergebnis fuer den aktuellen EPIC Fall

Nach Re-Import von app/tests/data/CDA-EPIC.xml und Export ueber
/fhir/medications/epic-cda/from-server?patient_id=<id>&count=100 sind folgende Felder im CDA sichtbar:
- recordTarget mit erweiterten Patientendaten
- medikationsfokussierte Sektion im Stil von CDA-EPIC.xml
- narrative List-Items im EPIC-Stil (`Medikation | Reason | Dosage`)
- effectiveTime/low
- doseQuantity
- strukturierter Medikamentencode, sofern aus translation im Import verfuegbar
- Pharmacode-Translation bei vorhandener Codierung
- klinisch nutzbare Kommentar-Notizen

## 5) Restliche Abhaengigkeiten

Wenn im FHIR MedicationStatement keine Route vorliegt, kann routeCode nicht exportiert werden.
Wenn im Quell-CDA keine verwertbaren strukturieren Codes vorhanden sind, bleibt nur der Identifier-/Text-Fallback.
