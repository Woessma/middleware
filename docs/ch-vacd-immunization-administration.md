# CH VACD Immunization Administration

Stand: 2026-11-04

## Zweck

Der Middleware-Endpoint `POST /cda/vacd/convert` erzeugt ein CH VACD
Immunization Administration Document auf FHIR R4. Die aktuelle interne
Profilpruefung verwendet die in HAPI installierten CH-VACD-/CH-Core-Profile
6.0.0. Die urspruengliche Versandorientierung an CH VACD 1.0.0 ist kein
Nachweis einer vollstaendigen Konformitaet mit diesen neueren Profilen.

## Interne Validierung und Korrekturen (2026-11-04)

Die lokale CDA-Testdatei wurde ohne Speicherung und ohne externen Versand
konvertiert und mit HAPI `Bundle/$validate` geprueft: 16 Ressourcen,
urspruenglich 13 Fehler. Nach den Codekorrekturen und Ergaenzung der fehlenden
Validator-Definition liefert das deployte System 0 Fehler, 27 Warnungen und
707 Hinweise. HTTP 200 allein ist kein Nachweis fuer Fehlerfreiheit.

- Die VACD-Composition traegt nicht mehr das unpassende CH-IPS-Profil.
- Immunizations ohne vorhandene Verification-Extension erhalten den
  VACD-SNOMED-Code `76104008` (nicht bestaetigt). Vorhandene explizite
  Bestaetigungen bleiben erhalten; ein CDA-Import bestaetigt keine Impfung.
- Fehlende Pflichtfelder einer Kontaktadresse werden mit FHIR
  `data-absent-reason=unknown` markiert, nicht mit erfundenen Adresswerten.
  Vorhandene Werte bleiben erhalten; Elternnamen-Kontakte benoetigen keine
  zusaetzliche Adresse.
- Der gemeinsame CDA-Allergie-Mapper verwendet `reaction.severity` statt des
  ungueltigen Top-Level-Felds `severity`. Ohne Reaktion wird der Schweregrad
  als Notiz erhalten, ohne eine Manifestation zu erfinden.
- 64 fokussierte Python-Regressionstests bestanden.

Behobener Validator-Blocker: Das installierte CH-Core-Adressprofil referenziert
`http://hl7.org/fhir/StructureDefinition/iso21090-codedString|5.3.0-ballot-tc1`.
Diese Definition fehlte in HAPI und verursachte Fehler in der
Adress-Extension-Slicing-Auswertung sowie im erforderlichen Patient-Slice.
Mit Zustimmung des Nutzers wurde die unveraenderte offizielle
StructureDefinition aus `hl7.fhir.uv.extensions.r4#5.3.0-ballot-tc1`
(FHIR 4.0.1) per PUT nach `StructureDefinition/iso21090-codedString`
importiert. Quelle:
https://packages.fhir.org/hl7.fhir.uv.extensions.r4/5.3.0-ballot-tc1
Canonical und Version wurden nach dem Import erneut gelesen und geprueft.
Ein Neustart war nicht erforderlich. Dies ersetzt nicht die Installation des
vollstaendigen Extension-Packages; bei einer neuen HAPI-Instanz muss diese
Abhaengigkeit ebenfalls bereitgestellt werden.

Die erneute Validierung erfolgte am laufenden Middleware-System mit derselben
CDA-Datei. Keine klinischen Ressourcen wurden gespeichert und kein externes
VACD-Ziel aufgerufen. Fehlerfreiheit dieser Stichprobe ist keine pauschale
Abnahme aller CDA-Varianten oder der verbleibenden Terminologiewarnungen.

Der Pfad ist für Dokumente mit verabreichten Impfungen gedacht. Er übernimmt nicht automatisch alle generischen CDA-Sections, sondern filtert auf die für CH VACD relevanten Ressourcen und Sections.

## Aktuelle Endpunkte

- Konvertierung: `POST /cda/vacd/convert`
- Validierung ohne Speicherung: `POST /cda/vacd/validate`
- HAPI-Import deaktiviert: `POST /cda/vacd/prepare` und
  `POST /cda/vacd/import` liefern HTTP 410 mit OperationOutcome.
- Separater externer Versand: `POST /cda/vacd/send` erfordert jetzt bei
  jedem Aufruf eine erfolgreiche interne CH-VACD-Validierung, sowohl vor
  dem ersten Zielkontakt als auch nach dem Umschreiben der Zielreferenzen.
  Fehler/fatal blockieren mit HTTP 422; Validator-Ausfall mit HTTP 502.
  Warnungen bleiben sichtbar und blockieren allein nicht.
  Beide Outcomes stehen bei erfolgreichem Versand unter `send.validation`.
  Scheitert die zweite Pruefung, wird kein Dokument gesendet; ein im
  vorhergehenden Schritt angelegter Zielpatient kann bereits existieren.

Die Validierung liefert das interne HAPI-OperationOutcome mit allen
Warnungen, nicht das Bundle. HTTP 200 ist allein kein Konformitaetsnachweis;
`issue.severity=error|fatal` ist ausschlaggebend.

## Historische Endpunkte und weiterhin deploytes Gateway-Routing

Die nachfolgend beschriebene Importvorbereitung ist inzwischen deaktiviert.

- Intern: `POST /cda/vacd/convert`
- Importvorbereitung: `POST /cda/vacd/prepare` (Bearer erforderlich,
  Transaction-Bundle ohne Write und ohne BridgeLink-Rueckaufruf)
- openEHR-Versand: `POST /cda/vacd/send`
- Eingabe: CDA als Multipart-Datei `file`, Formularfeld `raw_xml` oder Raw-Body
- Bundle-Typ: immer `document`

### BridgeLink-Routing (in OL_ROUTING eingerichtet)

| Externer Pfad | Middleware-Ziel | responseTarget |
|---|---|---|
| `/v1/cda/vacd/convert` | `/cda/vacd/convert` | `none` |
| `/v1/cda/vacd/import` | `/cda/vacd/prepare` | `hapi` |

Die Tabelle beschreibt die weiterhin deployte BridgeLink-Konfiguration.
Der Importpfad ist durch die Middleware gesperrt: deren HTTP 410 wird
von Destination 01 als Gateway-Fehler behandelt, ohne `fhirJson` fuer
Destination 02 zu setzen. Es findet kein HAPI-Import statt.
Die neue Validierung wird same-origin direkt ueber die Middleware aufgerufen;
ein Channel-Redeploy ist dafuer nicht erforderlich.

Der separate openEHR-Versand geht aus der Werkbank same-origin an
`/cda/vacd/send`, standardmaessig mit
`destination_base_url=https://vaccination-demo.raly.ch/api/fhir`.
Er legt gegebenenfalls einen Patienten auf diesem externen Ziel an und
sendet das Document-Bundle an dessen `/Bundle`-Endpunkt. Dies ist kein
direkter openEHR REST-Composition-Upload, sondern die FHIR-Schnittstelle
des openEHR-basierten Referenzservers.

Fuer externe Demo-Systeme ausschliesslich vollstaendig synthetische Daten
verwenden. Vorhandene CDA-Testdateien sind nicht automatisch anonymisiert.
Der hier dokumentierte Implementierungsstand bestaetigt noch keinen
erfolgreichen Live-Versand oder eine vollstaendige CH-VACD-Profilvalidierung.
Die Werkbank zeigt einen fehlerhaften `send`-Report auch bei HTTP 200 als
Fehler an; nur `send.status=sent` meldet erfolgreichen Versand.

Beispiel mit cURL:

```bash
curl -X POST "http://localhost:8000/cda/vacd/convert" \
  -H "Accept: application/fhir+json" \
  -F "file=@app/tests/data/CDA-EPIC.xml"
```

## Erwartete Bundle-Struktur

Das Ergebnis ist ein FHIR-R4-Dokumentbundle mit:

- `Bundle.type = document`
- `Bundle.identifier.system = urn:ietf:rfc:3986`
- UUID-Wert im Format `urn:uuid:<uuid>`
- `Bundle.timestamp`
- Composition als erstes `Bundle.entry`
- aufgelösten Referenzen auf die Bundle-`fullUrl`s

Das Ergebnis hat absichtlich `Bundle.type=document`, weil es ein fachliches
Dokument darstellt. Wird es über einen Middleware-Import weitergegeben, wird der
Bundle-Typ vor dem Versand automatisch auf `transaction` gesetzt und fehlende
`entry.request`-Angaben werden aus den Ressourcen ergänzt.

Offizielle Profile:

| Ressource | Profil |
| --- | --- |
| Bundle | `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-document-immunization-administration` |
| Composition | `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-composition-immunization-administration` |
| Immunization | `http://fhir.ch/ig/ch-vacd/StructureDefinition/ch-vacd-immunization` |

Die Composition verwendet zusätzlich die CH-Core-EPR-Profile:

- `http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition`
- `http://fhir.ch/ig/ch-core/StructureDefinition/ch-core-composition-epr`

## Sections und Ressourcen

Der VACD-Pfad behält die unterstützten CH-VACD-Sections anhand ihrer LOINC-Codes. Die Impfungen werden in der Section `11369-6` (`History of Immunization Narrative`) referenziert.

Nicht referenzierte generische Ressourcen wie `CareTeam` oder allgemeine Observations werden nicht in das CH-VACD-Dokument übernommen. Patient und Immunization werden als zentrale Dokumentressourcen behalten.

Die Composition enthält für die Dokumentmetadaten:

- Typ: SNOMED CT `41000179103`
- Kategorie: `urn:che:epr:ch-vacd:immunization-administration:2022`
- Vertraulichkeit: `N` mit CH-Core-EPR-Confidentiality-Extension und SNOMED CT `17621005` (`Normal`)

## Impfcode-Kette

Für bekannte Impfprodukte wird `Immunization.vaccineCode.coding` mit mehreren gleichwertigen Codings ausgegeben:

1. CVX: `http://hl7.org/fhir/sid/cvx`
2. SNOMED CT: `http://snomed.info/sct`
3. Swissmedic: `http://fhir.ch/ig/ch-vacd/CodeSystem/ch-vacd-swissmedic-cs`

Beispiele:

- Pfizer COVID-19: CVX `207`, SNOMED CT `1119349007`, Swissmedic-Produktcode
- Influenza: CVX `202`, SNOMED CT `346524008`, Swissmedic-Produktcode
- FSME: CVX `184`; ein produktbezogenes SNOMED-/Swissmedic-Mapping wird erst ergänzt, wenn der konkrete Impfstoff bekannt ist

Die CH-VACD-ValueSet ist produktbezogen. Ein generischer CVX-Code allein ist daher nicht zwingend Mitglied der ValueSet `ch-vacd-vaccines-vs`; für eine vollständig terminologisch bestätigte Ausgabe sollte der konkrete Swissmedic-Produktcode verwendet werden.

## Validierung

Für die vollständige Profilprüfung müssen mindestens folgende Packages geladen sein:

- `ch.fhir.ig.ch-core#7.0.0-ballot`
- `ch.fhir.ig.ch-term#3.4.0`
- `ch.fhir.ig.ch-vacd#1.0.0`

Die Middleware-Regressionsabdeckung liegt in `app/tests/test_vacd_convert.py` und prüft:

- Dokumentbundle und Profile
- Composition-first
- CH-VACD-Metadaten
- Filterung generischer Ressourcen
- Auflösung interner Referenzen

Ein frueherer Validatorlauf ohne geladene CH-VACD-Profile war kein
Konformitaetsnachweis. Massgeblich ist die interne HAPI-Pruefung mit den
geladenen Profilen und der oben dokumentierten behobenen Abhaengigkeit.
