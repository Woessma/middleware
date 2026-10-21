# EchoSOS zu FHIR

Stand: 2026-10-21

## Endpunkte und bestaetigter Status

Der externe BridgeLink-Aufruf ist:

```text
POST https://api.omnilink.ch/v1/echosos/resolveRequestResponse
```

Dieser Aufruf wurde am 2026-10-21 erfolgreich getestet: HTTP `200 OK`,
`Content-Type: application/json;charset=utf-8`, Laufzeit ca. `2176 ms`.
Die Antwort ist ein FHIR-Bundle mit `resourceType: Bundle` und
`type: transaction-response`. Der beobachtete Patient-Eintrag enthaelt
`response.status: 200 OK`, eine Location im Format
`Patient/{id}/_history/{version}`, `etag`, `lastModified` und ein
`OperationOutcome` mit informativem Issue.

Davon zu unterscheiden ist die direkte Middleware-Route:

```text
POST https://middleware.local.omnilink.ch/echosos/qr
```

Sie liefert nur das FHIR-Bundle mit `type: transaction` zurueck und schreibt
nicht selbst nach HAPI. Der externe Pfad `/v1/echosos/resolveRequestResponse`
wird von BridgeLink bereitgestellt, nicht von FastAPI.

Der Browserclient `echosos-fhir-test.html` verwendet den externen Endpunkt
direkt und sendet keinen zusaetzlichen FHIR-POST. Er prueft die Eintragsstatus
und Fehler-Issues der Transaction-Antwort und liest die Patient-ID aus
`response.location`. Patientensuche und `$everything` bleiben lesende
Aufrufe ueber `https://fhir.local.omnilink.ch/fhir/`.

## Ablauf

1. Der Client ruft den externen EchoSOS-Endpunkt auf; BridgeLink sendet
  EchoSOS-QR, Bild oder PKPass an die interne Route `POST /echosos/qr`.
2. Die Middleware dekodiert die QR-Daten und sucht den Patienten in HAPI anhand
  von Vorname, Nachname und Geburtsdatum. Mehrere Treffer werden abgewiesen.
3. Die Middleware erstellt ein FHIR-Transaction-Bundle mit Patient, Kontakten,
  Blutgruppe, Allergien, Vorgeschichte und gegebenenfalls Consent.
4. Die Middleware gibt das Bundle an BridgeLink zurück; sie schreibt die
  Ressourcen nicht selbst nach HAPI.
5. BridgeLink sendet das Bundle an HAPI und gibt dessen Transaction-Antwort
  (`type: transaction-response`) an den Client zurueck. Die einzelnen
  `entry[].response.status` und gegebenenfalls `OperationOutcome`-Issues
  muessen zusaetzlich zum HTTP-Status geprueft werden.
6. `$everything` ist ein separater Folgeaufruf von BridgeLink nach erfolgreichem
  Write. Die resultierenden Daten können in der EchoSOS-Notfallansicht
  dargestellt werden.

Der QR-Import und die manuelle Patientensuche verwenden damit denselben
FHIR-Gesamtdatenbestand.

## Deployment und Routenpruefung

Der aktuelle interne Middleware-Endpoint ist `POST /echosos/qr`, nicht
`/echosos/qr/import`. Extern gilt der oben dokumentierte BridgeLink-Endpunkt.
Das Docker-Image enthaelt eine Kopie des Quellcodes; Aenderungen werden nicht
automatisch in einen laufenden Container uebernommen. Nach einer Aktualisierung
im Projektverzeichnis neu bauen und den Dienst neu erstellen:

```bash
docker compose up -d --build middleware
```

Ein POST ohne Nutzdaten prueft die Route, ohne Patientendaten zu verarbeiten:

```bash
curl -i -X POST https://middleware.local.omnilink.ch/echosos/qr
```

Erwartet wird HTTP `400` mit
`{"detail":"No file provided (PKPass, PDF or QR code image)"}`.
HTTP `404` mit `{"detail":"Not Found"}` bedeutet dagegen, dass die erreichte
Instanz die Route nicht kennt. In diesem Fall auch direkt gegen
`http://127.0.0.1:8000/echosos/qr` pruefen, um Deployment und Proxy-Routing
zu unterscheiden.

## QR-Daten

Die Fragmentparameter des QR enthalten unter anderem:

- `n1`/`p1` bis `n3`/`p3`: bis zu drei Notfallkontakte
- `b`: Index der Blutgruppe, einschliesslich `Unbekannt`
- `a` und `r`: Allergie- und Reaktionsindizes; Reaktionen werden positionsweise
  den ausgewählten Allergien zugeordnet
- `d`: Indizes der medizinischen Vorgeschichte
- `m`: Medikamentenauswahlen
- `o` und `s`: Organspendeangaben ausserhalb bzw. im Schweizer Register
- `i`: sonstiger Freitext

Die Auswahlindizes werden entsprechend der öffentlich ausgelieferten
EchoSOS-Auswahllisten interpretiert. Der QR wird lokal dekodiert; für die
Auswahlwerte ist kein Abruf der persönlichen QR-URL erforderlich. Für
Patienten- und Identifier-Abgleiche führt die Middleware lesende Suchen in HAPI
aus; alle Writes erfolgen durch BridgeLink.

## Persistierte FHIR-Ressourcen

- `Patient`: Name, Geburtsdatum und bis zu drei Kontakte mit Beziehung `ECON`
- `Observation`: Blutgruppe mit LOINC `882-1`; der Patient ist Performer
- `AllergyIntolerance`: pro Allergie ein Eintrag, SNOMED-Codierung und optionale
  Reaktionsmanifestation; der Patient ist Recorder
- `Condition`: pro Vorgeschichtsauswahl ein Eintrag; der Patient ist Asserter
- `Consent`: bei expliziter Organspende-Zustimmung oder -Ablehnung; der Patient
  ist Patient und Performer

„Keine bekannten Allergien“ wird als SNOMED-CT `716186003` codiert. Die
Sammelauswahlen „Nierenversagen/Dialyse“ und
„Herzschrittmacher/Defibrillator“ werden ohne eindeutige Unterauswahl als
Quelltext gespeichert, damit keine der möglichen Diagnosen unbegründet
behauptet wird. Für nicht eindeutig spezifizierte Allergieauswahlen bleibt der
Originalbegriff erhalten.

Eine explizite Organspende-Zustimmung wird als `Consent.provision.type = permit`,
eine explizite Ablehnung als `deny` gespeichert. Verwendet werden Scope `adr`
und LOINC `42348-3` (`Advance directives`). Ein Schweizer Registereintrag
(`s=0`) gilt als Zustimmung. Ein fehlender Eintrag (`s=1`) ist keine Ablehnung;
„Keine Angabe“ und fehlende Werte erzeugen keinen Consent. Der QR enthält kein
Erklärungsdatum, daher wird keines ergänzt.

Medikamentenauswahlen und „Sonstiges“ werden derzeit zwar aus dem QR dekodiert,
aber noch nicht als eigene FHIR-Ressourcen persistiert.

## Kontaktmodell

Persönliche Kontakte werden doppelt nutzbar modelliert:

- `Patient.contact` ermöglicht die direkte Darstellung am Patienten.
- `RelatedPerson` ist die referenzierbare FHIR-Ressource der Kontaktperson.
- `Patient.contact.relationship` enthält fachliche Beziehungen.
- `ECON` kennzeichnet den Notfallkontakt.
- `HUSB` kennzeichnet den Ehemann.
- Sonstige Kontakte können mit einer passenden Beziehung wie `SPS` und der
  Kategorie `other` gespeichert werden.

Der Hausarzt wird nicht als persönlicher Kontakt gespeichert. Er wird als
`CareTeam.participant` mit Rolle `PCP` und einer Referenz auf `Practitioner`
modelliert. Bei CDA-Reimports bleiben vorhandene PCP-Teilnehmer erhalten,
wenn der neue CDA-Abschnitt keinen PCP enthält.

## Klinische Darstellung

Die fachliche Zusammenfassung zeigt:

- Vitalzeichen aus `Observation.category = vital-signs`
- Labor aus `Observation.category = laboratory`
- Sozialanamnese aus `Observation.category = social-history`
- Medikationen mit Dosierung, Autor, Status und Code
- Probleme, Allergien und Immunisierungen

Unklassifizierte Beobachtungen und `Encounter`-Ressourcen werden im
Notfallüberblick ausgeblendet. Technische Ressourcendetails werden nicht
angezeigt. Patient und fachliche Zusammenfassung sind standardmässig geöffnet.

## Blutgruppe

EchoSOS speichert die kombinierte Blutgruppe mit:

- LOINC `882-1`, `ABO and Rh group [Type] in Blood`
- `valueCodeableConcept`, zum Beispiel `A+` oder `0+`
- Kategorie `laboratory`

Wenn nur Einzelwerte vorhanden sind, werden ABO mit LOINC `883-9` und Rh mit
LOINC `10331-7` in der Anzeige kombiniert.

## Schwangerschaft

Der aktuelle Schwangerschaftsstatus wird als Observation gespeichert:

- LOINC `82810-3`, `Pregnancy status`
- SNOMED CT `77386006`, `Pregnant`
- Kategorie `social-history`

Eine aktive SNOMED-Condition `127364007` (`Primigravida`) kann zusätzlich in
der Problemliste geführt werden.

## Terminologie

LOINC- und SNOMED-Codings werden, soweit vom TX-Dienst unterstützt, gegen
`https://tx.fhir.ch/r4` geprüft. Schweizer Pharmacodes werden mit dem
NamingSystem `https://emediplan.ch/fhir/NamingSystem/pharmacode` gespeichert.
Sie bleiben zusätzlich als Medikamententext erhalten, werden aber nicht als
LOINC- oder SNOMED-Codes gegen TX validiert.

## Beispielabfrage

```bash
curl -H "Accept: application/fhir+json" \
  "https://fhir.local.omnilink.ch/fhir/Patient/{id}/%24everything?_count=500"
```

Die Antwort enthält Patient, `RelatedPerson`, `CareTeam`, `Practitioner`,
`Observation`, `Condition`, `MedicationStatement` und weitere verknüpfte
Ressourcen, sofern sie für den Patienten gespeichert sind.

Die lokalen EchoSOS-Identifier verwenden
`https://fhir.omnilink.ch/fhir/NamingSystem/...`. Bedingte Upserts suchen
zusätzlich anhand des Identifier-Werts, damit bereits gespeicherte Ressourcen
mit dem früheren Identifier-System beim Reimport wiedergefunden werden.
