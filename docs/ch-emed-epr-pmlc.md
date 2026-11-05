# CH-EMED-EPR-Medikationsliste: FHIR-Vorschau

Stand: 2026-11-05. Additiver, **nicht speichernder** Ausgabeweg.
PDF/A und QR folgen spaeter. Dieser Ausgabeweg veraendert keine HAPI-Daten;
die separate Importkorrektur/-pruefung ist in [Endpunkte](../ENDPOINTS.md) beschrieben.

## Aufruf

```http
POST /fhir/medications/pmlc/from-server?patient_id=<FHIR-ID>&language=de-CH&confidentiality=restricted
```

Kein Request-Body. Die Patient-ID ist zwingend; es gibt keine globale
Medikationssuche oder automatische Patientenauswahl.

Ein gueltiger Keycloak-Access-Token ist zwingend. Die Middleware prueft
RS256-Signatur, Issuer, erlaubten Client (`azp`), Ablaufzeit und gegebenenfalls
zusaetzlich konfigurierte Audience/Realm-Rolle
**vor** dem ersten Patientendatenabruf. Die Werkbank-Anmeldung allein
ersetzt diese Pruefung nicht.

Compose-Konfiguration:

```text
PMLC_KEYCLOAK_ISSUER=https://idp.omnilink.ch/realms/omnilink
PMLC_KEYCLOAK_ALLOWED_CLIENTS=app-omnilink-cardtest
PMLC_KEYCLOAK_AUDIENCE=
PMLC_KEYCLOAK_REQUIRED_ROLE=
```

Die Werkbank sendet ihren bestehenden Access-Token im Authorization-Header.
Auf ausdruecklichen Nutzerentscheid ist ihr signierter Client
`azp=app-omnilink-cardtest` erlaubt, ohne zusaetzliche Realm-Rolle.
Eine beliebige Anmeldung im selben Realm reicht nicht; fehlende/fremde
`azp` wird mit 403 abgewiesen. Die Allowlist ist eine kommaseparierte
Serverkonfiguration, kein Wert aus dem Request.
Eine konfigurierte Audience wird zusaetzlich geprueft. Sind sowohl
Client-Allowlist als auch Audience leer, bleibt der Abruf gesperrt (503);
ohne Token gilt 401. Nach Konfiguration Middleware neu erstellen.

Oeffentliche Signaturschluessel kommen ausschliesslich vom konfigurierten
Keycloak-Issuer, ohne Redirects; Cache maximal 5 Minuten. Dorthin gehen
weder Access-Token noch Patientendaten. Schluessel-/IdP-Ausfaelle sperren
den neuen Abruf mit 502. Bestehende Endpunkte erhalten keine neue
Authentifizierungslogik.

- `language`: `de-CH`, `fr-CH`, `it-CH`; Default `de-CH`.
- `confidentiality`: `normal`, `restricted`, `secret`; Default `restricted`.
  Bekannte strengere Vertraulichkeitsmarkierungen der Quelle duerfen nicht
  herabgestuft werden. Sicherheitsmarkierungen bleiben erhalten und werden
  auch in Bundle/Composition uebernommen.

Die Werkbank bietet **CH-EMED-EPR Medikationsliste: FHIR-Vorschau pruefen**
als Same-Origin-Aufruf. Kein neues BridgeLink-Routing erforderlich.
Sie zeigt den Pruefbericht nach Profil und bietet einen separaten Download
`ch-emed-epr-preview.json` fuer das Dokument. Der normale Antwortdownload
enthaelt weiterhin den gesamten Bericht.

## Quelle und Vollstaendigkeit

Technische Korrektur nach einem echten Vorschau-Bericht (2026-11-05):
Bundle und Composition verwenden denselben Dokument-Identifier. Die
Composition-Titel entsprechen dem PMLC-Profil (Medikationsplan /
Plan de médication / Piano farmacologico).
Die von CH Core 6.0.0 referenzierte Definition
`iso21090-codedString|5.3.0-ballot-tc1` wird unveraendert aus dem offiziellen
Paket `hl7.fhir.uv.extensions.r4#5.3.0-ballot-tc1` lokal ergaenzt; das
stabile Extensions-Paket 5.2.0 wird nicht ersetzt. Quelle:
https://packages.fhir.org/hl7.fhir.uv.extensions.r4/5.3.0-ballot-tc1
SHA-256 der Definition:
`ffecb4a9ce856afe4415d2dd02a3ae256948fb0f23bb470e337e51dd9b0ebb8d`.

Das getrennte Ausgabemapping ueberfuehrt `medicationCodeableConcept` oder
referenzierte Medication in eine enthaltene Medication mit lokaler Referenz.
Bereits enthaltene Medikationen bleiben enthalten. Die Ausgabekopie erhaelt
einen deterministischen UUID-Identifier; bereits passende UUID-Identifier
bleiben erhalten. Die Quell-Identifier werden in `Provenance.entity.what.identifier`
vollstaendig erhalten, nicht aus HAPI entfernt. Provenance nennt das
Software-Device und den echten Transformationszeitpunkt, keinen erfundenen
medizinischen Autor. Ein vorhandener Practitioner-Verweis wird in der Ausgabe
durch eine PractitionerRole mit genau diesem Practitioner repraesentiert;
eine unbekannte Organisation wird nicht ergaenzt.

Eindeutig bekannte UCUM-Dosiseinheiten (z.B. mg) erhalten fehlende
System-/Codeangaben; freie Einheitentexte werden nicht als UCUM ausgegeben.
Fehlende Therapieplan-/Vordokument-Referenzen,
medizinische Autoren-/Notizzeitpunkte oder dateAsserted werden nicht
erfunden. Zusammen mit der bewusst fehlenden PDF/A-Darstellung bleiben
diese Befunde sichtbar; die Vorschau ist nicht als fertiges EPR-Dokument
freigegeben.

Lokaler Replay desselben gelieferten Quellbestands nach den getrennten
Korrekturen: 29 Fehler / 9 Warnungen statt urspruenglich 52 / 10.
Dabei wurden weder HAPI-Daten geaendert noch die Vertraulichkeit abgesenkt.
Das ist eine technische Verbesserung, keine Freigabe des unvollstaendigen
EPR-Dokuments.

Nur `MedicationStatement?subject=Patient/<ID>&status=active` aus dem
konfigurierten internen HAPI wird gelesen. MedicationRequests werden weder
gesucht noch in die Liste gemischt. Identische Suchtreffer werden anhand
der Ressourcen-ID einmal uebernommen; verschiedene aktive Statements
werden nicht klinisch zusammengefuehrt.

Alle Suchseiten werden gelesen. Referenzierte Medikationen, Autoren,
Organisationen und andere unterstuetzte Begleitressourcen werden intern
aufgeloest. Contained-Ressourcen bleiben erhalten.
Unbekannte Referenztypen, fremde Patienten, nicht ausgewaehlte Statements,
widerspruechliche Treffer, fehlende Ressourcen und externe Links blockieren
den Vorgang ausdruecklich. Es wird kein still abgeschnittener Plan geliefert.

Grenzen: 50 Suchseiten, 1000 Ressourcen, 5 MiB finaler interner Input,
60 Sekunden Quell-Lesezeit und 120 Sekunden interne Generierungs-/Pruefzeit.
Source-Redirects und externe Pagination/Referenzabrufe sind deaktiviert.
Keine URL fuer ein anderes Quell- oder Zielsystem ist clientseitig waehlbar.

`status=active` ist nur der gespeicherte FHIR-Status. Dieser Ausgabeweg
prueft **nicht** klinisch, ob eine Therapie noch aktuell ist, und mischt
keine Rezepte als vermeintliche Einnahmebestätigung ein.

## Dokument und Validierung

Der interne Husky-Dienst verwendet die PMLC-Bundle-/Composition-Modelle
aus **Husky 3.5.0**. Neue Dokument-, Composition- und Device-IDs werden
erzeugt; Quellressourcen werden kopiert, lokale Referenzen auf eindeutige
`urn:uuid`-fullUrls umgeschrieben. Das Quelldokument wird nicht veraendert.
Dosismengen, medizinische Autoren- und Therapieplanangaben werden nicht
erfunden. Die getrennte technische Identifier-/Medication-Transformation
betrifft nur die Ausgabekopie. Die Composition nennt das erzeugende Software-Device, nicht
einen erfundenen behandelnden Arzt.

Geprueft wird das **exakte finale JSON**, das als `bundle` zurueckkommt,
gegen die lokal ausgelieferten Pakete:

- CH-EMED-EPR **3.0.0**
- CH-EMED **6.0.0**
- CH Core **6.0.0**
- CH Term **3.3.0**, HL7 Terminology R4 **7.0.1**
- die im Husky-Release enthaltenen EPR/MHD-/Extension-Abhaengigkeiten

Diese Pruefung verwendet Huskys internen HAPI-basierten Instance-Validator
ohne externen Terminologieserver. Sie ersetzt nicht `/fhir/validate` des
bestehenden HAPI-Servers; dessen Profilbestand wird nicht veraendert.
Der ausfuehrliche OperationOutcome wird uebernommen, nicht anhand
einzelner Warnungen als Erfolg interpretiert.

**Bewusste Grenze dieses ersten Ausbaus:** Das offizielle PMLC-Profil
verlangt eine lokale PDF/A-Originaldarstellung in
`Composition.section:originalRepresentation` mit Binary-Referenz.
Da der Nutzer PDF/A ausdruecklich auf spaeter verschoben hat, ist diese
FHIR-Vorschau noch **nicht profilkonform** und liefert den entsprechenden
Validierungsfehler. Es wird kein Platzhalter-PDF und kein Ersatzformat als
PDF/A ausgegeben. Weitere fehlende Pflichtangaben wie Therapieplanbezug,
Autorenzeitpunkt oder nicht ableitbare Dosierungsdetails bleiben ebenfalls
echte Fehler.

Keine separate Husky-Logikvalidierung oder klinische Reconciliation in
dieser Vorschau. `coverage.logicValidation=false` und
`coverage.clinicalReconciliation=false` kennzeichnen dies.
`coverage.originalRepresentationIncluded=false` macht die PDF/A-Luecke
maschinenlesbar.

## Antwort

```json
{
  "status": "invalid",
  "bundle": {"resourceType": "Bundle", "type": "document"},
  "validation": {"resourceType": "OperationOutcome", "issue": []},
  "coverage": {
    "profile": "http://fhir.ch/ig/ch-emed-epr/StructureDefinition/ch-emed-epr-document-medicationcard|3.0.0",
    "originalRepresentationIncluded": false,
    "logicValidation": false,
    "clinicalReconciliation": false
  },
  "source": {
    "patientId": "<FHIR-ID>",
    "activeMedicationStatements": 1,
    "medicationRequestsIncluded": false,
    "stored": false
  }
}
```

Gekuerztes Formbeispiel; der echte OperationOutcome enthaelt die
Pruefmeldungen. Keine Information aus `bundle` wird in HAPI gespeichert.

- **422**: Vorschau erzeugt, aber Validierung enthaelt error/fatal;
  Dokument und Outcome bleiben verfuegbar.
- **422 + OperationOutcome**: unbrauchbare/unvollstaendige Quelle,
  keine erzeugte Teilvorschau.
- **502 + OperationOutcome**: Quellserver, Engine oder Validator ausgefallen,
  ungueltige interne Antwort.
- **401/403**: fehlender/ungueltiger Token oder fehlende Realm-Rolle.
- **503**: Keycloak-Issuer oder weder Client-Allowlist noch Audience konfiguriert.
- **200** ist fuer eine spaetere fehlerfreie Ausgabe reserviert;
  Warnungen bleiben sichtbar. Im jetzigen Ausbau fehlt immer PDF/A.

Antworten tragen `Cache-Control: no-store`. Klinische Payloads werden
nicht geloggt. Die Java-Abhaengigkeiten verwenden einen NOP-Loggingprovider;
eigene Dienstfehler melden nur Fehlerklassen, die Middleware eigene
kontrollierte Fehlermeldungen.

## Tests

Python prueft Pagination, aktiven Status/Patientenzuordnung,
Referenzaufloesung, Quell-/Validatorausfaelle, Vertraulichkeit,
Groessen-/Ressourcengrenzen und Antwortstatus. Java prueft die echte
PMLC-Erzeugung samt lokalem Instance-Validator und unveraenderter Quelle.
Die bestehenden CDA-/FHIR- und Werkbanktests bleiben Teil der gezielten
Regression.

Herkunft, Isolation und Lizenzhinweise:
[Husky-Dienst](../husky-validator/README.md).
