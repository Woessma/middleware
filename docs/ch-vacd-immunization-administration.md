# CH VACD Immunization Administration

Stand: 2026-08-27

## Zweck

Der Middleware-Endpoint `POST /cda/vacd/convert` konvertiert ein CDA-Dokument in ein CH VACD Immunization Administration Document nach CH VACD 1.0.0 (STU 2 Ballot) auf FHIR R4. Für den openEHR-basierten Versand wird dieses Dokumentformat verwendet: https://fhir.ch/ig/ch-vacd/1.0.0/immunization-administration-document.html

Der Pfad ist für Dokumente mit verabreichten Impfungen gedacht. Er übernimmt nicht automatisch alle generischen CDA-Sections, sondern filtert auf die für CH VACD relevanten Ressourcen und Sections.

## Endpoint

- Intern: `POST /cda/vacd/convert`
- Über den Proxy: `POST /middleware/cda/vacd/convert`
- Eingabe: CDA als Multipart-Datei `file`, Formularfeld `raw_xml` oder Raw-Body
- Bundle-Typ: immer `document`

Beispiel mit cURL:

```bash
curl -X POST "https://fhir.woess.ch/middleware/cda/vacd/convert" \
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

Der aktuelle Validatorlauf meldet keine fatalen oder Fehler-Issues. Hinweise wie „Definition could not be found“ für CH-VACD-Profile bedeuten, dass das CH-VACD-Package im verwendeten Validator nicht geladen wurde.
