# Endpunkte und erwartetes Verhalten

## Basis-URLs

- BridgeLink FHIR Route (Proxy-Ziel noch offen): https://fhir.omnilink.ch/fhir/
- BridgeLink Middleware Route (Proxy-Ziel noch offen): https://fhir.omnilink.ch/middleware/
- BridgeLink intern auf `001-l-hlt01`: http://10.20.30.212:9080/
- Direkte Middleware-Adresse: https://middleware.local.omnilink.ch/
- HAPI intern aus der Middleware: http://hapi-fhir:8080/fhir
- Terminologie: https://tx.fhir.ch/r4
- VACD Send: https://vaccination-demo.raly.ch/api/fhir

### Bruno / aktueller Live-Aufruf

Für direkte Middleware-Requests wird aktuell die HTTPS-Adresse verwendet:

```text
https://middleware.local.omnilink.ch/
```

Beispiele:

```text
POST https://middleware.local.omnilink.ch/cda/convert?bundle_type=transaction
POST https://middleware.local.omnilink.ch/cda/import
```

Der direkte CDA-Import wurde mit `app/tests/data/CDA-AT.xml` erfolgreich
verarbeitet (`HTTP 200`, Transaction-Bundle mit 43 Einträgen). Dieser direkte
Aufruf konvertiert und validiert nur; er schreibt nicht nach HAPI.

Der vorgesehene BridgeLink-Pfad
`http://10.20.30.212:9080/middleware/cda/import` liefert aktuell `HTTP 404`.
Dadurch ist der Persistenzweg BridgeLink -> HAPI noch nicht aktiv.

## Beobachtung aus dem Live-System

Ohne gueltige BridgeLink-Authentifizierung antworten geschuetzte Endpunkte mit:

- HTTP Status: 401 Unauthorized
- Fehlerantwort von BridgeLink mit `401 Unauthorized` oder `403 Forbidden`

### Browser-Testclients und Keycloak

Die HTML-Testclients werden direkt über die Middleware-Domain ausgeliefert:

```text
https://middleware.local.omnilink.ch/test-client.html
```

Weitere Clients:

```text
https://middleware.local.omnilink.ch/echosos-fhir-test.html
https://middleware.local.omnilink.ch/fhir-query-client.html
https://middleware.local.omnilink.ch/epic-spital-emediplan-cda.html
https://middleware.local.omnilink.ch/card-analysis-test.html
```

Die Clients unterstützen Keycloak Authorization Code mit PKCE `S256`.
Issuer: `https://idp.omnilink.ch/realms/omnilink`. Im HTML wird die
öffentliche Client-ID eingegeben; ein Client Secret wird im Browser nicht
verwendet. Die jeweilige Redirect-URI, zum Beispiel
`https://middleware.local.omnilink.ch/test-client.html`, muss im Keycloak-Client freigeschaltet sein.

Das bedeutet: Die Root-URLs selbst sind nicht öffentlich erreichbar und müssen mit gültigen Zugangsdaten aufgerufen werden.

---

## 1) FHIR ueber BridgeLink: https://fhir.omnilink.ch/fhir/

Dieser Basis-Endpunkt ist der FHIR REST-API-Basispfad. Erwartet wird:

- Authentifizierung und Berechtigung durch BridgeLink
- FHIR-typische REST-Aufrufe wie z. B.:
  - `GET /fhir/Patient/...`
  - `GET /fhir/Observation/...`
  - `POST /fhir`
  - `PUT /fhir/ResourceType/id`
  - `GET /fhir/metadata`

### Erwartetes Verhalten

- Wenn keine Anmeldung vorliegt: `401 Unauthorized`
- Wenn gültig authentifiziert: FHIR-JSON-Antworten im Standardformat
- Typische Antwortformate:
  - `application/fhir+json`
  - `Content-Type: application/fhir+json`

### Beispiel

```http
GET https://fhir.omnilink.ch/fhir/Patient
Authorization: Bearer <JWT>
Accept: application/fhir+json
```

Erwartung:

- Erfolgreich: FHIR-Bundle mit Patient-Ressourcen
- Fehler: `404`, `400`, `401`, `500` je nach Resource und Anfrage

---

## 2) Middleware ueber BridgeLink: https://fhir.omnilink.ch/middleware/

Dieser Endpunkt ist der API-Basispfad der Middleware, nicht der FHIR-Server selbst. Die Middleware verarbeitet CDA-/FHIR-Umwandlungen und Imports.

### Erwartetes Verhalten

- Ohne gueltige BridgeLink-Authentifizierung: `401 Unauthorized`
- Mit gueltigem JWT und Berechtigung: Zugriff auf die freigegebenen Middleware-Endpunkte

### Aktueller Standardfluss

Der derzeitige Arbeitsweg ist:

- CDA wird per `POST /middleware/cda/import` an die Middleware gesendet
- Die Middleware wandelt das CDA in ein FHIR Bundle mit einer CH IPS Composition um. Die
  klinischen Ressourcen werden in den zugehörigen Composition-Sections referenziert.
- Import-Bundles ergänzen für FHIR-DomainResources eine generierte `Narrative`
  (`resource.text`), sofern die Ressource noch keine Narrative enthält. Ausgenommen
  sind Nicht-DomainResources wie `Bundle`, `Binary` und `Parameters`.
- Das Bundle wird an BridgeLink zur Weiterleitung an den FHIR-Server zurückgegeben
- BridgeLink schreibt das Bundle an den FHIR-Server und gibt dessen Ergebnis an den Client zurück

Die Python-Middleware selbst verwendet intern die Route `/cda/...`. Der Prefix
`/middleware` wird beim Aufruf über BridgeLink verwendet und ist nicht Teil der
internen FastAPI-Route.

Das ist der relevante Produktionsfluss, wenn wir Daten in den FHIR-Server importieren wollen.

### Typische Middleware-Endpunkte

| Methode | Pfad | Verhalten | Zweck |
|---|---|---|---|
| `GET` | `/middleware/` | Gibt `404` zurück | Root-Endpunkt der App |
| `GET` | `/middleware/metadata` | Nur im Debug-Modus aktiv; sonst `404` | Debug-Info |
| `POST` | `/middleware/cda/debug` | XML-Datei akzeptiert, parst CDA und gibt Profil/Patient/Header/Sections zurück | CDA-Diagnose/Debug |
| `GET` | `/middleware/test/patient` | Erstellt einen Test-Patienten | Test-/Smoke-Setup |
| `GET` | `/middleware/test/organization` | Erstellt eine Test-Organisation | Test-/Smoke-Setup |
| `POST` | `/middleware/cda/convert` | Erwartet CDA-XML; gibt FHIR Bundle JSON zurück | CDA -> FHIR Bundle |
| `POST` | `/middleware/cda/vacd/convert` | Erwartet CDA-XML; gibt VACD-optimiertes Bundle zurück | CH-VACD-Workflow |
| `POST` | `/middleware/cda/vacd/send` | Erwartet CDA-XML; konvertiert zu CH-VACD-Bundle, legt den Patienten beim Zielserver an und sendet das Bundle mit dessen zugewiesener ID | CH-VACD -> openEHR-FHIR-Referenzserver |
| `POST` | `/middleware/cda/import` | Erwartet CDA-XML; erzeugt und validiert ein Transaction-Bundle | CDA -> BridgeLink -> FHIR |
| `POST` | `/middleware/emediplan/convert` | Erwartet eMediplan-Text oder PDF/Bild mit QR-Code; gibt FHIR Bundle JSON zurück | eMediplan -> FHIR |
| `POST` | `/middleware/emediplan/import` | Erwartet eMediplan-Text oder PDF/Bild mit QR-Code; erzeugt und validiert ein Transaction-Bundle | eMediplan -> BridgeLink -> FHIR |
| `POST` | `/middleware/emediplan/import-bundle` | Erwartet JSON-Bundle; validiert und gibt es an BridgeLink zurück | Bundle -> BridgeLink -> FHIR |
| `POST` | `/middleware/emediplan/qr/convert` | Erwartet PDF oder Bild mit eMediplan-QR-Code; liest den QR-Code und gibt FHIR Bundle JSON zurück | eMediplan-QR (PDF/Bild) -> FHIR |
| `POST` | `/middleware/emediplan/qr/import` | Wie oben, erzeugt und validiert ein Transaction-Bundle | eMediplan-QR -> BridgeLink -> FHIR |
| `POST` | `/middleware/fhir/medications/epic-cda` | Erwartet FHIR Bundle JSON; liefert CDA-XML zurück | FHIR Bundle -> Epic CDA |
| `POST` | `/middleware/emediplan/epic-cda` | Erwartet eMediplan-Daten; konvertiert erst zu Bundle und dann zu CDA | eMediplan -> Epic CDA |
| `GET` | `/middleware/fhir/medications/epic-cda/from-server` | Holt Medikamente aus FHIR-Server und liefert CDA-XML zurück | FHIR -> Epic CDA |
| `POST` | `/middleware/cda/umzh/convert` | Erwartet CDA-XML; gibt UMZH-FHIR-Bundle zurück | UMZH-CDA -> Bundle |
| `POST` | `/middleware/cda/umzh/send` | Erwartet CDA-XML; konvertiert, sendet dann an Zielsystem | UMZH-Sendefluss |
| `POST` | `/middleware/hl7v2/convert` | Erwartet HL7v2 `ORU^R01`; gibt ein FHIR-Bundle mit Patient und Observations zurück | HL7v2 -> FHIR |
| `POST` | `/middleware/hl7v2/import` | Erwartet HL7v2 `ORU^R01`; konvertiert und importiert das FHIR-Bundle in den FHIR-Server | HL7v2-Import |
| `POST` | `/middleware/echosos/qr/import` | Erwartet EchoSOS-QR-Text, QR-Bild oder PKPass; erstellt/aktualisiert den Patienten und liefert danach `$everything` zurück | EchoSOS-Notfallpass-Import |
| `POST` | `/middleware/terminology/ValueSet/$expand` | Leitet FHIR-Parameters an `TERMINOLOGY_BASE_URL` weiter | ValueSet expandieren |
| `POST` | `/middleware/terminology/ValueSet/$validate-code` | Leitet FHIR-Parameters an `TERMINOLOGY_BASE_URL` weiter | Code validieren |
| `POST` | `/middleware/terminology/ConceptMap/$translate` | Leitet FHIR-Parameters an `TERMINOLOGY_BASE_URL` weiter | Codes übersetzen |
| `POST` | `/middleware/terminology/CodeSystem/$subsumes` | Leitet FHIR-Parameters an `TERMINOLOGY_BASE_URL` weiter | Codehierarchie prüfen |
| `POST` | `/middleware/terminology/ConceptMap/$closure` | Leitet FHIR-Parameters an `TERMINOLOGY_BASE_URL` weiter | Terminologie-Abschluss verarbeiten |

### eMediplan-Verordner und refdata.ch

`Medicaments[].PrscbBy` ist nach CHMED16A entweder eine GLN oder die
Freitextbezeichnung der verordnenden Person. Eine syntaktisch und per
GS1-Modulo-10 gueltige GLN erzeugt einen CH-Core-`Practitioner` mit:

```json
{
  "system": "urn:oid:2.51.1.3",
  "value": "7601009545993"
}
```

Wenn `REFDATA_API_KEY` konfiguriert ist, fragt die Middleware die refdata.ch
Partner-API best-effort ab und ergaenzt Name und Adresse. Ein Fehler oder ein
nicht gefundener Eintrag blockiert den Import nicht. Nicht als GLN erkennbare
`PrscbBy`-Werte werden unveraendert in
`MedicationStatement.informationSource.display` gespeichert. Das separate
CHMED16A-Feld `Auth` bezeichnet den Dokumentautor und wird nicht als
Verordner-GLN verwendet.

### HL7v2-Convert

`POST /middleware/hl7v2/convert` verarbeitet HL7v2-Nachrichten vom Typ `ORU^R01`.
Unterstützt werden:

- direkter Raw-Body mit `Content-Type: text/plain`
- Multipart-Datei mit dem Feld `file`
- Formularfeld `raw_hl7`

Verarbeitete Segmente:

- `MSH`, `PID`, `PV1`, `ORC`, `OBR`, `OBX`
- Patient, Adresse und Telefonnummer aus `PID`
- Laborwerte mit Einheit und Referenzbereich
- LOINC-Codings aus `OBX-3` mit `LN`
- lokale Codes wie `NA^Natrium` mit dem System
  `https://woess.ch/fhir/CodeSystem/hl7v2-local`
- HL7v2-Abweichungskennzeichnungen wie `LL` als FHIR-`interpretation`

LOINC-Codes werden automatisch zentral über TX validiert. Lokale Codes werden
übernommen, aber nicht gegen TX validiert.

`POST /middleware/hl7v2/import` verwendet dieselben Eingabeformen und gibt das
erzeugte Transaction-Bundle an BridgeLink zurück. BridgeLink schreibt es an den
FHIR-Server.

Beispiel Raw-Body:

```bash
curl -X POST \
  -H "Content-Type: text/plain" \
  --data-binary @message.hl7 \
  https://fhir.omnilink.ch/middleware/hl7v2/convert
```

Beispiel Datei-Upload:

```bash
curl -X POST \
  -F "file=@message.hl7" \
  https://fhir.omnilink.ch/middleware/hl7v2/convert
```

### Terminologie-Service

Der Middleware-Proxy verwendet standardmässig den Schweizer R4-Terminology-Server
`https://tx.fhir.ch/r4`. Die URL kann mit `TERMINOLOGY_BASE_URL` und der HTTP-Timeout
mit `TERMINOLOGY_TIMEOUT` (Sekunden) überschrieben werden. Der Request-Body muss eine
FHIR-`Parameters`-Ressource im Format `application/fhir+json` sein.

Unterstützte Operationen:

- `$lookup`
- `$validate-code`
- `$expand`
- `$translate`
- `$subsumes`
- `$closure`

Bei allen Convert- und Import-Pfaden wird eine Terminologie-Anreicherung und
Terminologieprüfung zentral auf dem erzeugten Bundle ausgeführt. Fehlende
`coding.display`-Werte werden für unterstützte CodeSysteme per TX `$lookup`
ergänzt. Identische Codings werden nur einmal gegen TX abgefragt; vorhandene
Displays werden nicht überschrieben.

Standardmässig arbeitet die Middleware im `report`-Modus. Nicht erreichbare oder
nicht unterstützte Terminologien blockieren die Konvertierung nicht. Für eine harte
Validierung kann gesetzt werden:

```yaml
environment:
  - TERMINOLOGY_VALIDATION_MODE=strict
```

Die lokale Medikamenten-Map bleibt für Pharmacode, GTIN, Swissmedic-Produktnummer,
Produktbeschreibung und Abgabekategorie zuständig. TX wird ergänzend für die
Validierung verwendet. CVX wird intern auf SNOMED CT abgebildet, da CVX auf TX nicht
verfügbar ist. ICD-10 und ICD-11 werden derzeit übernommen, aber nicht über TX geprüft.

### Verhalten nach Endpunkt-Typ

#### 1. Pure Convert-Endpunkte
Diese Endpunkte wandeln Input in ein FHIR Bundle oder in XML um, aber sie importieren nichts direkt.

Beispiele:

- `POST /middleware/cda/convert`
- `POST /middleware/cda/vacd/convert`
- `POST /middleware/emediplan/convert`
- `POST /middleware/cda/umzh/convert`

Erwartung:

- `200 OK` mit JSON- oder XML-Ergebnis bei gültigen Inputdaten
- `400 Bad Request` bei fehlendem Input oder ungültigem Format
- `500 Internal Server Error` für interne Fehler

Wichtig: `POST /middleware/cda/convert` liefert ein Bundle zurück. BridgeLink kann dieses Bundle als separaten Schritt an den FHIR-Server senden:

```http
POST <FHIR-Server-Route ueber BridgeLink>/fhir
Authorization: Bearer <JWT>
Content-Type: application/fhir+json
Accept: application/fhir+json
```

Das bedeutet: Der Ablauf kann auch so aussehen:

1. `POST /middleware/cda/convert` mit CDA-Daten
2. Ergebnis: FHIR Bundle JSON
3. BridgeLink sendet das Bundle an die FHIR-Server-Route

So ist der Convert-Call nicht der eigentliche Import, sondern die Vorstufe fuer den direkten FHIR-Write ueber BridgeLink.

#### 2. BridgeLink-Import-Endpunkte
Diese Endpunkte erzeugen und validieren ein Transaction-Bundle. BridgeLink schreibt
das Bundle anschließend in den FHIR-Server.

Beispiele:

- `POST /middleware/cda/import`
- `POST /middleware/emediplan/import`
- `POST /middleware/emediplan/import-bundle`

Erwartung:

- `200 OK` mit einem validierten FHIR-Transaction-Bundle
- `400 Bad Request` bei ungültigem Input
- Der HAPI-FHIR-Status kommt erst aus dem nachgelagerten BridgeLink-Write

#### 3. Conversion-to-XML-Endpunkte
Diese Endpunkte liefern als Output XML statt JSON.

Beispiele:

- `POST /middleware/fhir/medications/epic-cda`
- `POST /middleware/emediplan/epic-cda`
- `GET /middleware/fhir/medications/epic-cda/from-server`

Erwartung:

- `Content-Type: application/xml`
- `200 OK` bei gültiger Konvertierung
- `400` bei ungültigem Input
- `500` bei internen Exceptions

#### 4. Send-/Workflow-Endpunkte
Diese Endpunkte verarbeiten einen kompletten Workflow mit Konvertierung + Versand.

Beispiele:

- `POST /middleware/cda/umzh/send`
- `POST /middleware/cda/vacd/send`

Erwartung:

- Rückgabe mit zwei Blöcken:
  - `convert`: Workflow-Informationen
  - `send`: Versandreport / Status des Zielsystems

`POST /middleware/cda/vacd/send` richtet sich an einen openEHR-basierten CH-VACD-
Referenzserver (z. B. `https://vaccination-demo.raly.ch/api/fhir`, Default via
`VACD_SEND_BASE_URL`, ueberschreibbar per Query-Parameter `destination_base_url`).
Ablauf:

1. CDA wird wie bei `/cda/vacd/convert` zu einem CH-VACD-Document-Bundle konvertiert.
2. Die enthaltene `Patient`-Ressource wird zunaechst beim Zielserver gesucht, um
   Duplikate zu vermeiden (analog zum Find-or-Create-Ablauf gegen den eigenen
   FHIR-Server in `services/patient_service.py`): zuerst per `GET
   {ziel}/Patient?identifier=<system>|<value>` je Identifier der Ressource; lehnt der
   Zielserver diesen Suchparameter ab (z. B. der raly.ch-Demoserver, der nur `name`
   unterstuetzt), erfolgt ein Fallback per `GET {ziel}/Patient?name=<Nachname>`,
   bestaetigt durch exakten Abgleich von `birthDate`. Nur wenn kein Treffer gefunden
   wird, erfolgt ein `POST {ziel}/Patient` (mit `active: true`, falls nicht gesetzt, da
   der Zielserver dieses Feld verlangt). In allen Faellen wird die (gefundene oder neu
   zugewiesene) `id` verwendet.
3. Im Bundle werden `Patient.id` auf diese ID aktualisiert und ein `identifier` mit
   `system=urn:che:epr:ch-vacd:ehr-id` und dieser ID ergaenzt. Anschliessend werden
   fuer **alle** Entries `fullUrl` und interne Referenzen auf das im offiziellen
   CH-VACD-Beispiel dokumentierte Schema umgestellt (siehe
    `https://fhir.ch/ig/ch-vacd/1.0.0/Bundle-1-1-ImmunizationAdministration.json.html`):
   `fullUrl` wird zu `<ziel>/<ResourceType>/<id>` (absolut), referenzierende Felder
   (`subject.reference`, `patient.reference`, `performer.actor.reference`, Section-
   Entries usw.) werden zur relativen Form `<ResourceType>/<id>` aufgeloest statt
   `urn:uuid:`-Referenzen zu verwenden.
4. Das aktualisierte Bundle wird per `POST {ziel}/Bundle` an den Zielserver gesendet.

`outbound_authorization` (Query-Parameter) wird unveraendert als `Authorization`-
Header an beide Aufrufe (Patient und Bundle) weitergereicht.

### Schreiben eines Bundles ueber BridgeLink

Wenn ein fertiges FHIR Bundle vorliegt, sendet BridgeLink es nach der
Berechtigungspruefung an den FHIR-Server. Die Middleware liefert das Bundle nur
zurueck und schreibt nicht selbst nach HAPI FHIR.

```http
POST <BridgeLink-FHIR-Route>
Authorization: Bearer <JWT>
Content-Type: application/fhir+json
Accept: application/fhir+json
```

Das Ergebnis des BridgeLink-Schreibens wird an den aufrufenden Client
zurueckgegeben.

### Import-Stabilisierung in der Middleware

Die Import-Endpunkte stabilisieren den Payload vor dem Versand an `FHIR_BASE`:

- Eine einzelne FHIR-Ressource wird als `Bundle.type=transaction` mit einem Entry verpackt.
- Ein Bundle mit `type=document` wird für den Import in `type=transaction` umgewandelt.
- Fehlt bei einem Bundle-Entry `request.method` oder `request.url`, werden die Angaben aus der Ressource erzeugt.
- Ressourcen mit ID erhalten `PUT ResourceType/{id}`; Ressourcen ohne ID erhalten `POST ResourceType`.
- Doppelte Ressourcen werden anhand ihrer fachlichen Identität oder ihres Payloads entfernt.
- Identifier-basierte `POST`-Einträge erhalten zusätzlich eine `ifNoneExist`-Bedingung.

Damit können auch die von `/cda/vacd/convert` und `/cda/etoc/convert` erzeugten
Dokumentbundles direkt über einen Importpfad weiterverarbeitet werden. Der
Convert-Endpunkt selbst bleibt ein reiner Konvertierungsschritt.

Beispiel für eine einzelne Ressource:

```json
{
  "resourceType": "Patient",
  "id": "p1",
  "name": [{"family": "Muster", "given": ["Max"]}]
}
```

Diese Eingabe wird intern zu einem Transaction-Entry mit `PUT Patient/p1`.

### Praktischer Ablauf fuer einen Import ueber BridgeLink

1. Ein gültiges FHIR Bundle als JSON erzeugen.
2. Für ein Bundle muss `entry` eine Liste mit Ressourcen enthalten.
3. `type` kann `transaction` sein; ein Dokumentbundle wird beim Middleware-Import automatisch umgewandelt.
4. Jede `entry.resource` muss ein gültiges FHIR-Resource-Objekt sein.
5. `request.method` und `request.url` können im Middleware-Import fehlen und werden automatisch ergänzt.
6. Das JSON ueber die BridgeLink-FHIR-Route an HAPI FHIR senden.

### Beispiel für direktes Schreiben

```bash
curl -u "USERNAME:PASSWORD" \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  -X POST "https://fhir.omnilink.ch/fhir" \
  --data @bundle.json
```

Beispiel-JSON:

```json
{
  "resourceType": "Bundle",
  "type": "transaction",
  "entry": [
    {
      "resource": {
        "resourceType": "Patient",
        "id": "p1",
        "name": [
          {
            "family": "Muster",
            "given": ["Max"]
          }
        ]
      },
      "request": {
        "method": "PUT",
        "url": "Patient/p1"
      }
    }
  ]
}
```

### Beispiel für den Middleware-Weg

```http
POST http://10.20.30.212:9080/middleware/cda/import
Authorization: Bearer <JWT>
Content-Type: multipart/form-data
```

Erwartung:

- `200 OK` mit Import-Status, falls das CDA valid ist und der FHIR-Server akzeptiert
- `400 Bad Request` bei ungültigem XML oder fehlenden Input
- `500 Internal Server Error` bei internen Fehlern
- `502`/Fehler aus dem FHIR-Server, falls der Import dort fehlschlägt

---

## Allgemeine Regeln

- Beide Endpoints sind per HTTP Basic Auth geschützt.
- Das FHIR-Backend erwartet FHIR-konforme Payloads mit `application/fhir+json`.
- Die Middleware erwartet typischerweise XML- oder JSON-Inputs je nach Route.
- Die Root-URLs selbst liefern ohne gültige Authentifizierung nur 401.

## Kurzfassung

- `https://fhir.omnilink.ch/fhir/` = FHIR-Route ueber BridgeLink, Read und FHIR-Write
- `https://fhir.omnilink.ch/middleware/` = Middleware-Route ueber BridgeLink fuer Convert und Bundle-Erzeugung

Wenn du möchtest, kann ich daraus auch noch eine sauberere Version mit Swagger-ähnlicher Tabellenstruktur oder eine Version für externe Stakeholder im Projekt-Style machen.
