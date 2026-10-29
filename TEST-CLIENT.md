# FHIR Middleware Test Client

`test-client.html` ist eine Browser-Werkbank für die fachlichen Middleware-
Use-Cases. Sie verarbeitet FHIR JSON, CDA XML, HL7v2 und eMediplan-Payloads und
stellt auch EPIC-CDA-, UMZH-, Terminologie- und Smoke-Test-Pfade bereit.
Der freigegebene CDA-Import verwendet Keycloak Authorization Code mit PKCE
und leitet authentifizierte Requests an
`https://api.omnilink.ch/v1/cda/convert` weiter. Die Client-ID
`app-omnilink-cardtest` ist wie beim EchoSOS-Client verborgen vorbelegt.
Ausgewaehlte UTF-8-XML-Dateien werden ohne Multipart-Huelle als Raw-Body
mit `Content-Type: application/xml; charset=UTF-8` gesendet. Fuer eingefuegten
XML-Text gilt derselbe Header. FHIR-`OperationOutcome`-Fehler und fehlgeschlagene
Bundle-Eintraege werden auch bei HTTP 200 als Fehler angezeigt.
Die POST-Anzeige nennt den oeffentlichen CDA-Endpunkt; der Request verwendet
weiterhin den internen Same-Origin-Proxy.

## Auf der Testlab-VM öffnen

Die HTML-Dateien werden vom Middleware-Service ausgeliefert und müssen nicht
mehr separat über `python3 -m http.server` gestartet werden:

```bash
curl -I https://middleware.local.omnilink.ch/test-client.html
```

Danach im Browser öffnen:

```text
https://middleware.local.omnilink.ch/test-client.html
```

Alternativ ist der lokale Port `8082` verfügbar:

```text
http://localhost:8082/test-client.html
```

## Card Analysis Service testen

`card-analysis-test.html` testet den generischen Card-Analyse-Endpunkt direkt.
Die Seite unterstützt QR-Daten aus der Kamera, Bilddateien, `.pkpass`, MRZ-
Text und Versicherungs-Kartenfotos per OCR. Dabei werden sichtbare Felder wie
Name, Vorname, Geburtsdatum, Versicherungsnummer und Krankenkasse erkannt. Im
Feld **Card Analysis Endpoint** kann lokal
standardmäßig `https://middleware.local.omnilink.ch/card/analyze` oder die erreichbare
Middleware-Route eingetragen werden.

Die Kamera liest den aufgedruckten Karteninhalt als Bild. Einen elektronischen
Chip oder NFC-Inhalt kann dieser Browser-Flow nicht auslesen; dafür wäre ein
separater NFC-Kartenleser mit eigener Geräteintegration erforderlich.

```text
https://middleware.local.omnilink.ch/card-analysis-test.html
```

Der verwendete Endpoint ist:

```text
POST /card/analyze
```

## EchoSOS + FHIR kombiniert

`echosos-fhir-test.html` verbindet den EchoSOS-Import mit der Patientensuche.
Die Anmeldung erfolgt ausschliesslich ueber Keycloak (Authorization Code mit
PKCE), mit vorbelegter Client-ID `app-omnilink-cardtest`. Die Redirect-URI
`https://middleware.local.omnilink.ch/echosos-fhir-test.html` muss im
Keycloak-Client freigeschaltet sein. Der kompakte Bereich „Input auswählen“
zeigt wie die Card-Analysis-Seite nur „Mit Keycloak anmelden“ und den
tatsaechlichen Tokenstatus; die Client-ID ist verborgen vorbelegt.
Basic Auth und lokale Passwortspeicherung werden nicht mehr verwendet; alte gespeicherte
EchoSOS-Zugangsdaten werden beim Laden entfernt.
Nach dem Login kann ein EchoSOS-QR mit der mobilen Kamera, als Bild oder als
PKPass-Datei eingelesen werden. Die Middleware sucht den Patienten nach Name
und Geburtsdatum und erstellt ein Transaction-Bundle. BridgeLink schreibt es
nach HAPI; der Browser sendet keinen weiteren FHIR-POST.
Vor dem Import dekodiert `/echosos/preview` die Eingabe ohne FHIR-Schreibzugriff.
Der Browser sendet anschliessend nur den geprueften `source_url`-EchoSOS-Link
als `text/plain; charset=utf-8` ueber `/echosos/import` an BridgeLink, nicht
erneut die Bild- oder PKPass-Datei. Eine fehlgeschlagene Vorschau oder ein
ungueltiger Link verhindert den Import.
Die Antwort wird als Patientenuebersicht und aufklappbare FHIR-Ressourcen
visualisiert. Nach dem Speichern wird automatisch
`Patient/{id}/$everything?_count=500` abgefragt, sodass auch vorhandene
FHIR-Kontakte, PCP-Referenzen und klinische Daten sichtbar werden.
Auf breiten Bildschirmen belegt die Eingabe ein Drittel und die
FHIR-Visualisierung zwei Drittel der Spaltenbreite. Bis 860 Pixel
Bildschirmbreite werden die Bereiche untereinander angezeigt.
Die Allergietabelle zeigt auch alle gespeicherten Reaktionen (einschliesslich
vorhandener Beschreibung, Schweregrad, Beginn und Expositionsweg),
Verifizierungsstatus, Typ und Kategorien. Fehlende Angaben werden als
„nicht angegeben“ dargestellt; eine Reaktionsschwere wird nicht als
Kritikalitaet der Allergie interpretiert. Technische FHIR-Felder bleiben unter
„Alle Ressourcen und Felder“ einsehbar.
Neue EchoSOS-Allergieangaben, einschliesslich „keine bekannten Allergien“,
werden als `unconfirmed` mit dem Patienten als `asserter` importiert und als
„Unbestaetigt – Patientenangabe“ angezeigt. Beim Wiederimport bleiben vorhandene
Verifizierungsstatus und Quellenangaben erhalten. Historische automatisch
gesetzte `confirmed`-Werte werden nicht pauschal rueckwirkend geaendert.

```text
https://middleware.local.omnilink.ch/echosos-fhir-test.html
```

Der Import verwendet:

```text
POST /echosos/import
```

Die Middleware leitet diesen authentifizierten Same-Origin-Aufruf an den
festen BridgeLink-Endpunkt `https://api.omnilink.ch/v1/echosos/resolve`
weiter. So muss der Browser keine Cross-Origin-Anfrage an BridgeLink senden.
Der Client prueft das `transaction-response`-Bundle einschliesslich aller
Eintragsstatus und Fehler-Issues. Die Patient-ID wird aus
`entry[].response.location` gelesen. Patientensuche und der separate
`$everything`-GET laufen ueber `/echosos/fhir/Patient/...` als Same-Origin-
Middleware-Proxy an `FHIR_BASE`. Ein Fehler beim anschliessenden Lesen wird
ausdruecklich vom bereits erfolgreichen Import unterschieden.

### Offener Keycloak-Login (Stand 2026-10-21)

Der Live-Login der EchoSOS-Seite ist noch nicht erfolgreich bestaetigt:
Keycloak meldet fuer `app-omnilink-cardtest`
`Invalid parameter: redirect_uri`. Die funktionierende Anmeldung der
Card-Analysis-Seite gibt die EchoSOS-Ruecksprungadresse nicht automatisch frei.

In der Keycloak-Administration unter Realm `omnilink` -> Clients ->
`app-omnilink-cardtest` -> Settings -> **Valid redirect URIs** muss exakt
dieser Eintrag gespeichert sein:

```text
https://middleware.local.omnilink.ch/echosos-fhir-test.html
```

Bestehende Eintraege, insbesondere fuer `card-analysis-test.html`, beibehalten.
Nicht die komplette `/protocol/openid-connect/auth?...`-Anmelde-URL eintragen.
**Web origins** und **Valid post logout redirect URIs** ersetzen diese
Login-Freigabe nicht. Als Web Origin gilt
`https://middleware.local.omnilink.ch`.
Nach dem Speichern die Anmeldung von der EchoSOS-Seite neu starten.
Die tatsaechlich gespeicherte Keycloak-Konfiguration wurde hier nicht
eingesehen oder geaendert.

UI, Tokenstatus, Import und lesende Folgeabfragen wurden im Browser mit
simulierten Antworten und einem synthetischen Token geprueft. Das ist kein
Nachweis fuer einen erfolgreichen Live-Keycloak-Login oder End-to-End-Import
aus dem Browser.

## FHIR-Abfragen visualisieren

`fhir-query-client.html` fuehrt lesende Abfragen ueber BridgeLink gegen den FHIR-Server
und zeigt bei einer enthaltenen Patient-Ressource zuerst die Stammdaten,
Kontaktinformationen, Adressen und Notfallkontakte. Danach folgen die fachliche
Zusammenfassung. In der EchoSOS-Notfallansicht sind Patient und fachliche
Zusammenfassung standardmaessig aufgeklappt. Alle Ressourcen und Felder sind
zusaetzlich strukturiert aufklappbar; Encounter und weitere Beobachtungen
werden nicht mehr ausgeblendet.
Zusätzlich fasst die Seite vorhandene klinische Einträge als Tabellen zusammen:
Vital Signs, Laborbefunde, Sozialanamnese, Medikationen, Probleme, Allergien und
Unvertraeglichkeiten sowie Immunisierungen. Leere Bereiche werden ausgeblendet.
Die klinischen Tabellen zeigen neben der Bezeichnung auch den FHIR-Code und das
zugehoerige Codesystem; bei Observations wird zudem der Messwert angezeigt.
Die Tabelle **Medikationen** zeigt zusaetzlich den Verordner aus
`MedicationStatement.informationSource`. Referenzierte Practitioner werden mit
Name und GLN angezeigt, zum Beispiel `Dr. Anna Beispiel (GLN: 7601009545993)`.
Liegt nur eine Freitextbezeichnung ohne GLN vor, erscheint der ausdrueckliche
Hinweis `(GLN: nicht vorhanden)`.
Bei `Composition`-Ressourcen werden die Sections inklusive Entry-Referenzen als
Tabelle dargestellt.
In der EchoSOS-Notfallansicht sind Patient und fachliche Zusammenfassung
standardmaessig aufgeklappt. Impfungen stehen mit Anzahl, Datum, Impfstoff,
Charge, Durchfuehrenden und Status am Anfang. Bei fehlenden Impfungen wird
dies fuer die geladene Patient-ID explizit angezeigt. `$everything`-Folgeseiten
werden automatisch geladen; alle Ressourcen und Felder bleiben zugaenglich.

Die QR-Vorschau verwendet vor dem Import den schreibfreien lokalen Decoder
`POST /echosos/preview`. Sie zeigt alle erkannten Angaben einschliesslich
weiterer Notfallkontakte, Allergiereaktionen, Medikamenten, Vorgeschichte,
Organspende und Freitext sowie aufklappbare Originalparameter.
Eine Vorschau ist keine Speicherbestaetigung: Medikamente und Freitext
werden derzeit nicht als eigene klinische FHIR-Ressourcen gespeichert.

Die obere Übersicht zeigt außerdem Blutgruppe und Schwangerschaftsstatus.
Die voreingestellte Abfrage ist:

```text
Patient/{patientId}/$everything?_count=500
```

Nach Eingabe einer Patient-ID und Klick auf **Abfrage ausfuehren** laedt die
voreingestellte Abfrage beispielsweise:

```text
http://10.20.30.212:9080/fhir/Patient/123/$everything?_count=500
```

Der Platzhalter `{patientId}` im Abfragepfad wird ersetzt. Die Auswahl
**Ressource** stellt Vorlagen mit dem Entwicklungswert `_count=500` fuer MedicationStatement,
AllergyIntolerance, Immunization, Observation, Condition, Encounter,
DiagnosticReport, DocumentReference und ServiceRequest bereit. Der Abfragepfad
kann weiterhin fuer andere GET-Abfragen direkt angepasst werden, etwa
`Patient?_count=50`. Fuer den geschuetzten FHIR-Server Basic Auth oder Bearer
Token auswaehlen. Der Button **Zugangsdaten speichern** speichert Auth-Typ,
Username und Passwort beziehungsweise Token in diesem Browser; der Button
**Gespeicherte Zugangsdaten loeschen** entfernt sie wieder.

Lokal öffnen:

```text
http://localhost:8082/fhir-query-client.html
```

## Konfiguration

- **BridgeLink Middleware Route**: Lokal standardmäßig `http://10.20.30.212:9080/middleware/`.
- **BridgeLink FHIR Route**: Lokal standardmäßig `http://10.20.30.212:9080/fhir/`.
- **Auth Typ**: Standard ist Basic Auth; alternativ keine Authentifizierung oder Bearer Token.
- **Username**: wird nur für Basic Auth verwendet.
- **Password / Token**: Fallback für Basic Auth oder manuellen Bearer Token.

Für den bevorzugten Login wird die Client-ID im Feld **Keycloak Client-ID**
eingegeben. **Mit Keycloak anmelden** verwendet den Realm `omnilink` mit
Authorization Code und PKCE `S256`; das Access-Token wird nur in der Browser-
Session gehalten und als Bearer-Token an BridgeLink gesendet. Ein Client Secret
gehört nicht in HTML und wird deshalb nicht abgefragt.

Zugangsdaten werden nur für den jeweiligen Browser-Request verwendet. Die Seite
speichert sie nicht dauerhaft.

Bei Basic Auth und Bearer Token blockiert der Client den Request, solange die
benötigten Zugangsdaten fehlen. So wird kein browserseitiger Basic-Auth-Dialog
durch einen versehentlichen Request ohne `Authorization`-Header ausgelöst.
HTTP-401-Antworten von Nginx werden als Authentifizierungsfehler angezeigt,
ohne die HTML-Fehlerseite in die Antwortansicht zu übernehmen.
Bei Passwörtern mit Sonderzeichen versucht der Client nach einem 401 automatisch
einmal die klassische Basic-Auth-Kodierung als Fallback. Die Requests laufen als
Same-Origin-Requests, damit der explizit gesetzte `Authorization`-Header vom
Browser nicht durch eine zu strikte Credential-Policy unterdrückt wird.

## Use Cases

Die Auswahl gruppiert die verfügbaren Abläufe nach FHIR Bundle, CDA,
CDA-Profilen, UMZH, HL7v2, eMediplan, EPIC CDA, Terminologie und Smoke Tests.
Abhängig vom Use Case erscheinen die benötigten Query-Parameter und ein passendes
Beispiel. Text- und JSON-Dateien können direkt in den Eingabebereich geladen
werden. Die eMediplan-Pfade akzeptieren ausserdem PDF- und Bilddateien mit
QR-Code als binaeren Multipart-Upload.

Der Use Case **Patient $everything** ruft den FHIR-Endpunkt ueber BridgeLink
auf. Ein im Browser geoeffneter Direktlink enthaelt Zugangsdaten nicht automatisch
und kann daher mit `401 Unauthorized` scheitern.

**Use Case ausführen** sendet den Payload mit der angezeigten HTTP-Methode an den
angezeigten Pfad. JSON wird vor dem Versand geparst. CDA und HL7v2 werden als
roher Body gesendet; der CDA-Debug-Pfad verwendet einen Multipart-Dateiupload.
HTTP-Status, Laufzeit und Antworttyp erscheinen über der Antwort.

**Als Eingabe verwenden** uebernimmt die letzte JSON- oder XML-Antwort in den
Editor. Damit kann beispielsweise ein CDA zunaechst konvertiert und das erzeugte
Bundle anschliessend stabilisiert oder ueber BridgeLink an FHIR gesendet werden.

**Antwort herunterladen** speichert die letzte Antwort passend zum Content-Type
als JSON-, XML- oder Textdatei.

**Verbindung prüfen** prüft parallel `GET /fhir/stabilize` an der Middleware und
`GET /metadata` am FHIR-Server. Beim Middleware-Pfad gilt `405 Method Not
Allowed` als erreichbar, da der eigentliche Endpunkt nur POST akzeptiert.

Der UMZH-Sendepfad kann die Ziel-URL und Outbound-Autorisierung als Parameter
übergeben. Da die aktuelle API den Autorisierungswert als Query-Parameter
akzeptiert, sollte diese Funktion nur in einer kontrollierten Testumgebung
verwendet werden.

## Eingabeformat

Der Editor erwartet gültiges JSON mit `resourceType`. Möglich sind beispielsweise:

```json
{
  "resourceType": "Patient",
  "id": "patient-1",
  "name": [{"family": "Muster", "given": ["Max"]}]
}
```

Oder ein bereits vorbereitetes Transaction-Bundle:

```json
{
  "resourceType": "Bundle",
  "type": "transaction",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "patient-1"
      },
      "request": {
        "method": "PUT",
        "url": "Patient/patient-1"
      }
    }
  ]
}
```

## Sicherheit

Die Oberfläche ist für Entwicklung und Smoke-Tests gedacht. Keine echten
Produktivdaten oder dauerhaften Zugangsdaten im Browser verwenden. Für Requests
an geschützte externe Systeme müssen Authentifizierung und CORS serverseitig
zugelassen sein.
