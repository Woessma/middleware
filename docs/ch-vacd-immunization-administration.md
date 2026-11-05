# CH VACD Immunization Administration

Stand: 2026-11-05

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
- Zusaetzliche Husky-Pruefung aus CDA: `POST /cda/vacd/husky/validate`
- Bestehendes FHIR-Document mit Husky pruefen: `POST /fhir/vacd/husky/validate`
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

## Patientenabgleich und inkrementeller Versand (2026-11-05)

`POST /cda/vacd/send` verwendet weiterhin die FHIR-Fassade des externen
openEHR-Referenzservers, keinen direkten openEHR-REST-Import:

1. Internes Dokument validieren. Fehler oder Validator-Ausfall verhindern
   jeden Zielkontakt.
2. Patienten-Identifier mit System und Wert am Ziel suchen. Alle
   Identifier-Treffer muessen auf denselben Patienten verweisen.
   Explizit nicht unterstuetzte Identifier-Suche erlaubt den Fallback auf
   Familiennamensuche mit lokalem exaktem Vergleich von Familienname,
   erstem Vornamen und Geburtsdatum (Namen ohne Beachtung der Grossschreibung).
   Kein Treffer: Patient anlegen. Ein eindeutiger Treffer: wiederverwenden.
   Mehrdeutigkeit oder widerspruechliche Identifier: HTTP 409, kein Versand.
   Ohne ausreichend pruefbare Identitaet wird kein Patient angelegt.
3. Fuer bestehende Patienten `Immunization?patient=Patient/<id>` am Ziel lesen.
   Fehlerhafte, unvollstaendige oder paginierte Suchantworten blockieren;
   sie werden niemals als leere Trefferliste interpretiert. Auch als ignoriert
   erkennbare Suchfilter blockieren. Eine vollstaendige Pagination ist in
   diesem Pfad noch nicht implementiert.
4. Vorhandene Impfungen anhand gleicher Identifier erkennen. Ohne gemeinsame
   Identifier erfordert die automatische Erkennung gemeinsamen Impfcode
   (System und Code), identischen `occurrenceDateTime`-Wert und gleiche,
   nicht leere Charge. Klinische Felder muessen uebereinstimmen;
   aufloesbare Bundle-/Zielreferenzen werden vor dem Vergleich normalisiert.
   Gleicher Impfcode und Zeitpunkt ohne eindeutige Charge oder abweichende
   klinische Daten erfordern manuelle Klaerung (HTTP 409). Es gibt kein
   Fuzzy-Matching und keine automatische Korrektur vorhandener Impfungen.
   Dieselben Regeln gelten fuer doppelte Impfungen im Eingangsdokument.
5. Nur neue Impfungen behalten. Bei Teilimport erhalten Bundle und
   Composition eine neue Dokumentkennung; `Composition.relatesTo` verweist,
   soweit vorhanden, mit `transforms` auf die urspruengliche
   Composition-Kennung. Entfernte Impfreferenzen werden aus Sections
   entfernt und die Impfnarrative aus den verbleibenden Impfungen neu
   erzeugt. Das Quellbundle bleibt unveraendert. Kein stilles Loeschen
   von Impfungen im Ziel.
6. Exakten finalen Payload nach Umbau und Referenzumschreibung erneut intern
   validieren. Nur bei erfolgreicher Pruefung `POST /Bundle`.

Der Bericht enthaelt `send.immunizations.new` und `.skipped`.
Ohne neue Impfungen ist `send.status=skipped` mit
`reason=no-new-immunizations` ein erfolgreicher No-op, kein Dokumentversand.
Bereits verarbeitete identische Quelldokumente liefern
`reason=document-already-processed`. Die Werkbank zeigt diese Faelle
ausdruecklich als **kein Versand**, nicht als gesendetes Dokument.

Die Werkbank zeigt oberhalb der internen Validierungen eine eigene
Uebersicht **Externer FHIR-Server: Ergebnis**: Patientenanlage oder
Wiederverwendung, Zielpatient-ID, neue/ausgelassene Impfungen, externer
Dokument-HTTP-Status sowie Kennung, Zeitstempel und Ressourcentyp-Zaehler
der Zielantwort. Die unveraenderte externe Antwort ist separat aufklappbar.
Die Uebersicht verwendet ausschliesslich den vorhandenen Sendereport;
kein weiterer externer Request und keine zusaetzliche Speicherung.
Ressourcen im zurueckgegebenen Document-Bundle belegen nicht einzeln deren
Neuanlage oder Aenderung. Es wird weder eine unabhaengige Lesepruefung noch
eine nicht bestaetigte openEHR-Composition-/EHR-Anlage behauptet.

### Persistenz, Parallelitaet und Wiederaufnahme

`VACD_IMPORT_DB` bezeichnet das SQLite-Versandregister; Standard:
`/var/lib/omnilink/vacd/imports.sqlite3`. Compose bindet dafuer das Named
Volume `vacd-import-state` ein. Ohne Compose muss dieses Verzeichnis
schreibbar und dauerhaft gemountet sein. Die Persistenz gehoert zum
Betriebskonzept und darf bei Redeployments nicht verworfen werden.

Pro normalisierter Ziel-URL wird der gesamte Abgleich/Versand mit einem
Dateilock serialisiert. Alle beteiligten Middleware-Worker muessen dasselbe
Register samt Lock-Verzeichnis mit funktionierenden POSIX-Locks verwenden.
Das Register enthaelt nur Hashes fuer Ziel, Dokumentkennung und CDA-Inhalt
sowie den Verarbeitungszustand, keine CDA-/FHIR-Payloads oder Patientennamen.
Eine wiederverwendete Dokumentkennung mit veraendertem Quellinhalt wird
als Konflikt abgewiesen; neue CDA-Versionen benoetigen eine neue Kennung.
Ohne Composition-Identifier dient der SHA-256 des Quell-CDA als Schluessel.

Vor Patientenanlage bzw. Dokument-POST wird ein ausstehender Schreibvorgang
persistiert. Ein Timeout, Abbruch oder nicht bestaetigter Write blockiert
weitere Aufrufe fuer dieses Ziel mit HTTP 409, auch nach Prozessneustart.
Es erfolgt kein automatischer Retry eines moeglicherweise ausgefuehrten
Writes. Betreiber muessen den Zielzustand pruefen und danach gezielt den
betroffenen Registereintrag abgleichen/freigeben; nicht pauschal das Register
leeren. Profilfehler vor dem Dokument-POST setzen keinen ausstehenden
Dokument-Write. Ein zuvor angelegter Patient kann trotzdem bestehen bleiben.

Diese Absicherung gilt fuer diese Middleware mit gemeinsamem Register.
Andere Sender oder getrennte Register benoetigen weiterhin zielseitige
atomare Identitaets-/Dublettenregeln. Der Zielserver weist eine solche
Garantie im CapabilityStatement nicht aus. Eine FHIR-Patient-ID wird hier
gemaess bestehendem Referenzserververtrag als VACD-EHR-Identifier verwendet;
dies ist kein allgemeiner Nachweis einer openEHR-`ehr_id`-Zuordnung.

Abnahme mit einem offiziellen synthetischen CH-VACD-6.0.0-Beispiel:
eine vorhandene und eine neue Impfung wurden zu einem Dokument mit genau
einer neuen Impfung umgebaut. Die echte interne HAPI-Pruefung des finalen
Payloads lieferte 0 Fehler/fatal, 8 Warnungen und 20 Hinweise. Externe
Patientenanlage und Dokument-POST waren dabei gemockt; es erfolgten keine
externen Writes und keine klinische Speicherung. Dies ist keine
Live-Abnahme des Referenzservers.

### Testdeployment und externer Antwortnachweis

Am 2026-11-05 wurden Patientenabgleich, inkrementeller Versand,
persistentes Register und Ergebnisansicht auf dem Testsystem deployt.
46 VACD-Python- und 22 Werkbank-Node-Tests bestanden. Dienststatus und
Ergebnisansicht wurden geprueft; das Register blieb beim Redeployment erhalten.

Die vom Benutzer bereitgestellte Antwort eines Testaufrufs weist
`send.status=sent`, `patient.matched_existing=false`, drei neue und keine
ausgelassenen Impfungen sowie Dokument-HTTP-Status 201 aus. Die externe
Antwort ist ein Document-Bundle mit einer Composition, einem Device,
einem Patienten und drei Immunizations. Das belegt einen erfolgreichen
Dokumentaufruf nach Rueckmeldung des Zielservers. Eine unabhaengige
Lesepruefung und die direkte openEHR-Speicherung sind damit nicht belegt.
Patientendaten und konkrete Patientenkennungen werden nicht in Git abgelegt.

### Anlage mit Bruno lesend pruefen

In Bruno eine Umgebungsvariable `vacd_base` mit
`https://vaccination-demo.raly.ch/api/fhir` und `patient_id` mit dem Wert
aus `send.patient.assigned_id` setzen. Fuer beide Requests:

```text
Accept: application/fhir+json
```

Patient lesen, Methode **GET**, kein Body:

```text
{{vacd_base}}/Patient/{{patient_id}}
```

Erwartung: HTTP 200, `resourceType=Patient` und die angefragte ID.

Impfungen lesen, Methode **GET**, kein Body:

```text
{{vacd_base}}/Immunization?patient=Patient/{{patient_id}}
```

Das Suchbundle nach `entry[].resource` auswerten: Patientreferenz,
Impfcode, `occurrenceDateTime`, Charge und Quell-Identifier vergleichen.
Bei `link.relation=next` auch Folgeseiten lesen. Die Anzahl kann durch
spaetere Importe hoeher sein als im einzelnen Versandreport.
Keinen erneuten POST zur Lesepruefung ausfuehren. Auf dem oeffentlichen
Demo-System ausschliesslich synthetische Patientendaten verwenden.

## Zusaetzliche Husky-Pruefung (2026-11-05)

Korrektur nach einem Bericht mit zwei Fehlern fuer `COVID-19-PFIZER`:
Der Impfstoffmapper erzeugt keine kuenstlichen Swissmedic-Codes wie
`COVID-19-PFIZER`, `COVID-19-MODERNA` oder `INFLUENZA` mehr. Aus einem
COVID-Markennamen wird auch nicht mehr pauschal CVX 207 abgeleitet;
Hersteller allein belegt keine konkrete Formulierung. Vorhandene
Quellcodes inklusive CodeSystem, Identifier, Datum und Charge bleiben
erhalten. Ungueltige Quellcodes werden nicht still entfernt, sondern
weiterhin validiert. Eine konkrete Swissmedic-Zuordnung benoetigt eine
belegte Produktidentitaet. HAPI-Altdaten werden nicht automatisch geaendert.

Der Husky-Outcome nennt das angeforderte Dokumentprofil in der Top-Level-
Extension `urn:omnilink:validation:profile`. Meldungen mit eindeutigem
`Bundle.entry[n].resource`-Pfad erhalten die deklarierten Ressourcenprofile
als `urn:omnilink:validation:context-profile`. Das ist **Kontext**, keine
Behauptung, welches einzelne Profil den Befund ausgeloest hat. Fuer
Contained-Pfade wird kein Elternprofil zugeordnet. Die Werkbank zeigt
explizite Profilangaben vorrangig, danach Ressourcenprofil-Kontext oder
den Prueflauf mit dem Hinweis auf fehlende Einzelprofilzuordnung.
Fehler und Warnungen werden weiterhin genau einmal gezaehlt.

Regression: 36 Python-, 21 Java- und 28 Node-Tests bestanden. Im deployten
System liefert ein offizielles synthetisches VACD-Beispiel mit erhaltener
CVX-Quellcodierung und korrigiertem Mapping 0 Fehler / 6 Warnungen. Wird
der erfundene Swissmedic-Code wieder hinzugefuegt, wird es mit 422
abgewiesen; der Befund enthaelt den Immunization-Profilkontext.
Dies ist kein erneuter Test der urspruenglichen CDA-Datei: der geteilte
Bericht enthaelt nur das OperationOutcome, nicht das Quelldokument.
Keine Speicherung, kein externer Versand.

Die beiden neuen Endpunkte sind eigenstaendige Prueflaeufe, kein neuer
Konverter und kein Ersatz fuer die HAPI-Sendesperren. Der XML-Weg benutzt
die bestehende VACD-Konvertierung; der JSON-Weg prueft das eingereichte
Document unveraendert. Beide liefern ein OperationOutcome, kein Bundle.
HTTP 200 ohne Fehler/fatal, 422 bei Profilfehlern, 400 bei unpassender Eingabe,
502 bei Engine-Ausfall. Die Werkbank zeigt Fehler und Warnungen nach Profil.

Der interne Husky-3.5.0-Dienst verwendet dieselbe Husky/HAPI-Instance-Engine
wie Huskys `ChVacdValidator`, aber explizit **CH-VACD 6.0.0** passend zum
installierten HAPI-Profilbestand. Huskys Defaultpakete mit CH-VACD /
CH Core `7.0.0-ballot` werden nicht uebernommen. Fuer VACD und PMLC wird eine
gemeinsame serialisierte Engine verwendet, kein zweiter grosser Validator
im begrenzten Container. Bestehende PMLC- und CDA-Pruefungen bleiben aktiv.

Lokal gebuendelt: CH-VACD 6.0.0, CH Core 6.0.0, CH Term 3.3.0,
HL7 Terminology R4 7.0.1 und Extensions R4 5.2.0. Kein txServer, keine
Paketdownloads im Request. Maximal 5 MiB FHIR-JSON. Es wird immer das
versionierte Immunization-Administration-Dokumentprofil geprueft;
zusaetzliche deklarierte Profile bleiben erhalten und werden ebenfalls
geprueft. Unbekannte deklarierte Profile werden explizit als Fehler gemeldet.

Dies ist eine technische Instance-/Profilpruefung, keine klinische
Impfempfehlung, Dublettenentscheidung oder vollstaendige Terminologiefreigabe.
Kein HAPI-Write oder externer Versand. Der Husky-Validator ruft keine
Patienten ab; der CDA-Weg behaelt die vorhandenen read-only
Patienten-/Referenzabgleiche der Konvertierung bei.

Offizielles CH-VACD-Paket (CC0-1.0):
https://packages.fhir.org/ch.fhir.ig.ch-vacd/6.0.0
SHA-256:
`f44f958d44603a0d3b0e73e8503d76317338c03ea8965886364f795cc515777d`.

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
`send.status=skipped` ist ein erfolgreicher No-op ohne Dokumentversand.

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
