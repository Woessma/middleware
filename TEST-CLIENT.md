# FHIR Middleware Test Client

`test-client.html` ist eine Browser-Werkbank für die fachlichen Middleware-
Use-Cases. Sie verarbeitet FHIR JSON, CDA XML, HL7v2 und eMediplan-Payloads und
stellt auch EPIC-CDA-, UMZH-, Terminologie- und Smoke-Test-Pfade bereit.

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
Nach dem Login kann ein EchoSOS-QR mit der mobilen Kamera, als Bild oder als
PKPass-Datei eingelesen werden. Die Middleware sucht den Patienten nach Name
und Geburtsdatum, legt ihn bei Bedarf an beziehungsweise aktualisiert ihn,
speichert Notfallkontakt und Blutgruppe und laedt danach `Patient/{id}/$everything`.
Die Antwort wird als Patientenuebersicht und aufklappbare FHIR-Ressourcen
visualisiert. Nach dem Speichern wird automatisch
`Patient/{id}/$everything?_count=500` abgefragt, sodass auch vorhandene
FHIR-Kontakte, PCP-Referenzen und klinische Daten sichtbar werden.

```text
https://middleware.local.omnilink.ch/echosos-fhir-test.html
```

Der Import verwendet:

```text
POST /echosos/qr/import
```

## FHIR-Abfragen visualisieren

`fhir-query-client.html` fuehrt lesende Abfragen ueber BridgeLink gegen den FHIR-Server
und zeigt bei einer enthaltenen Patient-Ressource zuerst die Stammdaten,
Kontaktinformationen, Adressen und Notfallkontakte. Danach folgen die fachliche
Zusammenfassung. In der EchoSOS-Notfallansicht sind Patient und fachliche
Zusammenfassung standardmaessig aufgeklappt; technische Ressourcendetails,
Encounter und unklassifizierte Beobachtungen werden dort ausgeblendet.
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
standardmaessig aufgeklappt. Technische Ressourcendetails, Encounter und
unklassifizierte Beobachtungen werden dort ausgeblendet.

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
