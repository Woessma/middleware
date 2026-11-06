# Endpunkte und erwartetes Verhalten

Stand: 2026-11-05

## Basis-URLs

- BridgeLink FHIR Route: https://fhir.local.omnilink.ch/fhir/
- Externe CDA-Konvertierung (ohne Write): https://api.omnilink.ch/v1/cda/convert
- Externer CDA-Import (mit HAPI-Write): https://api.omnilink.ch/v1/cda/import
- Externe eMediplan-Konvertierung (ohne Write): https://api.omnilink.ch/v1/emediplan/convert
- Externer eMediplan-Import (mit HAPI-Write): https://api.omnilink.ch/v1/emediplan/import
- Externer EchoSOS-Endpunkt: https://api.omnilink.ch/v1/echosos/resolve
- BridgeLink intern auf `001-l-hlt01`: http://10.20.30.212:9080/
- Direkte Middleware-Adresse: https://middleware.local.omnilink.ch/
- HAPI intern aus der Middleware: http://hapi-fhir:8080/fhir
- Terminologie: https://tx.fhir.ch/r4
- VACD Send: https://vaccination-demo.raly.ch/api/fhir

## Status

### CH-EMED-EPR-FHIR-Vorschau aus aktiven Medikationen

`POST /fhir/medications/pmlc/from-server?patient_id=<FHIR-ID>`
liest ausschliesslich aktive MedicationStatements dieses Patienten
aus dem internen HAPI und erzeugt mit Husky eine PMLC-FHIR-Vorschau.
Optional `language=de-CH|fr-CH|it-CH` und
`confidentiality=normal|restricted|secret` (Default restricted).
Keine MedicationRequests, keine Speicherung, kein PDF/QR.
Vor dem Lesen erfolgt eine lokale Keycloak-Signatur-/Issuer-/Ablaufpruefung.
Der bestehende Werkbank-Token wird uebernommen; standardmaessig ist
`PMLC_KEYCLOAK_ALLOWED_CLIENTS=app-omnilink-cardtest` ueber den signierten
`azp`-Claim erlaubt, ausdruecklich ohne zusaetzliche Realm-Rolle.
Eine gesetzte `PMLC_KEYCLOAK_AUDIENCE` wird zusaetzlich geprueft.
Ohne Allowlist und Audience bleibt der Leseweg deaktiviert.
401/403 kennzeichnen Auth-Fehler, 503 eine fehlende Auth-Konfiguration.

Die finale Vorschau wird intern gegen CH-EMED-EPR 3.0.0 / CH-EMED 6.0.0 /
CH Core 6.0.0 mit lokal gebuendelten Paketen validiert. Der bestehende
HAPI-Profilbestand und `/fhir/validate` bleiben unveraendert.
Antwort: `bundle`, `validation` (OperationOutcome), `coverage`, `source`.
error/fatal ergibt 422 mit Dokument und Bericht; Engine-/Quellfehler 502.

Die vorgeschriebene PDF/A-Originaldarstellung fehlt im ersten Ausbau
bewusst. Damit ist die Ausgabe noch nicht profilkonform; dies wird
ausdruecklich als Validierungsfehler angezeigt, nicht als Erfolg.
[Quelle, Abdeckung und Antwortvertrag](docs/ch-emed-epr-pmlc.md).

### CDA-Eingangsvalidierung mit Husky

`POST /cda/source/validate?level=full|xsd` prueft das originale CDA-XML,
ohne FHIR-Konvertierung oder Speicherung. Raw-XML, Multipart `file` und
Form `raw_xml` werden akzeptiert; maximal 5 MiB CDA-Inhalt.
Die Werkbank verwendet diesen Endpunkt same-origin.

Der interne Husky-Dienst hat keinen Hostport. Die CDA-R2-XSD ist aktiv.
`full` ist der Default und verlangt zusaetzlich passende Profil-Schematrons.
Fuer die untersuchten EPIC/C-CDA- und AT-Arztbrief-Templateversionen sind
noch keine exakt passenden offiziellen Regeln installiert; dies ergibt
einen ausdruecklichen `not-supported`-Fehler, auch bei gueltiger XSD.
`xsd` behauptet keine Profilkonformitaet.

Das OperationOutcome enthaelt Fehler/Warnungen und explizite
CDA-Pruefgruppen fuer die Werkbank. HTTP 200 bedeutet nicht Fehlerfreiheit.
Leere Eingabe liefert 400, uebergrosse Eingabe 413, Dienst-/Enginefehler 502.
Bestehende Convert-/Importwege und HAPI-Validierungen bleiben unveraendert.
Abdeckung, Herkunft, Isolation und Betrieb:
[Husky-Dienst](husky-validator/README.md).

### Separate Validierung ohne Speicherung

Die Werkbank bietet CDA- und VACD-Validierung als Same-Origin-Aufrufe zur
Middleware an; neue BridgeLink-Routen sind dafuer nicht erforderlich.
`POST /cda/validate` akzeptiert dieselben XML-Eingaben wie Convert und
`bundle_type=transaction|document`. `POST /cda/vacd/validate` erzeugt immer
ein CH-VACD-Dokument. Beide liefern das originale interne HAPI-
OperationOutcome als `application/fhir+json`, nicht das konvertierte Bundle.

Mit `POST /fhir/validate` lassen sich bereits konvertierte Bundles aus
beliebigen CDA-Use-Cases (auch eTOC/UMZH) separat pruefen. Der JSON-Body
ist direkt das Bundle. Es wird nicht stabilisiert, angereichert oder
gespeichert. Geprueft werden FHIR R4 und die tatsaechlich deklarierten
Profile; dies fuegt keine fehlenden Profildeklarationen hinzu.

HTTP 200 bedeutet eine ausgefuehrte Pruefung, nicht Fehlerfreiheit:
`issue.severity=error|fatal` kennzeichnet Validierungsfehler. Warnungen,
Diagnostik und betroffene Felder bleiben unveraendert sichtbar; die Werkbank
zeigt auch Fehler in einem HTTP-200-Outcome als Fehler an.
Nicht erreichbarer Validator, unerwartete HTTP-Antworten oder ungueltige
Outcomes liefern HTTP 502 mit Fehler-OperationOutcome. Ein anderer
Ressourcentyp als Bundle liefert bei `/fhir/validate` HTTP 400.
Gueltige Fehler-OperationOutcomes des Validators bei HTTP 400/422 werden
mit Originalstatus und vollstaendiger Diagnostik weitergereicht, etwa bei
nicht parsebaren FHIR-Werten.
Die Zieladresse ist ausschliesslich das konfigurierte interne `FHIR_BASE`;
Clients koennen kein externes Validierungsziel angeben.

Andere Importwege erhalten dadurch noch keine automatische Validierungssperre.

### Beratende CH-EMED-Validierung fuer eMediplan (2026-11-06)

`POST /emediplan/validate` akzeptiert dieselben Eingaben wie
`/emediplan/convert` (eMediplan-JSON, CHMED16A0/1, Multipart `file` oder
Form-Feld `raw_payload`; bei PDF/Bild wird der eMediplan-QR-Code lokal
dekodiert). Die Pruefkopie des konvertierten Bundles wird in die
CH-EMED-Struktur transformiert und intern mit HAPI geprueft: Medications
werden als contained Ressourcen mit `#`-Referenzen eingebettet,
Statement-Identifier deterministisch als `urn:uuid` abgebildet und der
Verschreiber (GLN-Practitioner oder Freitext) in PractitionerRole-Eintraege
gekapselt. Zusaetzlich zu den deklarierten Profilen wird das strikte Profil
`ch-emed-medicationstatement` (CH EMED 6.0.0) auf allen MedicationStatements
deklariert und mitgeprueft. Die Antwort ist das OperationOutcome, nicht das
Bundle. Fehlt am Medikament ein Verschreiber (`PrscbBy`), dient die
Plan-Autoren-GLN (`Auth`) als informationSource-Fallback; dieser Fallback
gilt auch fuer Convert/Import.

Die Pruefung ist bewusst **nur beratend**: Convert-, Prepare- und Importwege
liefern weiterhin die CH-Core-Struktur mit eigenstaendigen
Medication-Eintraegen und eMediplan-Identifiern (Basis fuer Upsert- und
Dublettenabgleich) und werden durch Befunde nicht blockiert. HTTP 200
bedeutet eine ausgefuehrte Pruefung, nicht Fehlerfreiheit; 400 bei
ungueltiger Eingabe, 502 bei Validatorausfall.

### Verpflichtende Medikations-Importpruefung (2026-11-05)

Getrennt von der EPR-Ausgabe: CDA-Importe verwenden `/cda/prepare`;
eMediplan (Text, FHIR-JSON, QR) verwendet wie bisher `/emediplan/prepare`
bzw. die entsprechenden Middleware-Importfunktionen. Der letzte Schritt
nach Terminologie-, Patienten-/Dublettenabgleich prueft das tatsaechlich
zurueckgegebene Transaction-Bundle intern mit HAPI. Medikationsressourcen
erhalten mindestens ihr CH-Core-Profil; vorhandene Profile bleiben erhalten
und werden ebenfalls geprueft. Unbekannte deklarierte Profile blockieren.
422 bei error/fatal (auch wenn HAPI HTTP 200 liefert), 502 bei Pruefausfall,
kein BridgeLink-/HAPI-Write im abgewiesenen Schritt. Warnungen allein
blockieren nicht; ihre Anzahl wird protokolliert.
Ohne Medikationsressourcen bleibt das bisherige Verhalten erhalten.
`/fhir/convert` wendet dieselbe Pruefung auf Medikationsbundles an;
reine Convert-/Stabilize-Endpunkte werden nicht zu Importen umgedeutet.

**CDA-Gateway muss neu deployt werden:** Die lokalen OL_ROUTING-/Channel-XMLs
wurden auf `/v1/cda/import -> /cda/prepare` umgestellt. Die bisher laufende
Route `/cda/convert` ist noch keine Importsperre. Datei-Aenderung allein
aendert den Live-Channel nicht. Siehe [BridgeLink](bridgelink/README.md).

Importmapping: unzweideutige direkte CDA-Medikationsautoren werden mit
Identifier und `dateAsserted` strukturiert erhalten; eigene Entry-Notizen
erhalten vorhandene Autoren-/Zeitangaben. Verschachtelte Kommentarautoren
oder reine Therapiezeiten werden nicht als Assertion-Zeit ausgegeben.
Fehlender/unbekannter CDA-Medikationsstatus wird als `unknown` gespeichert,
nicht mehr automatisch `active`. Bestehende Dupletten-Identifier bleiben
unveraendert. Keine automatische Migration vorhandener HAPI-Daten.

### Zusaetzliche VACD-Pruefung mit Husky (2026-11-05)

- `POST /cda/vacd/husky/validate`: CDA als Raw-XML, Multipart `file`
  oder Formular `raw_xml`; verwendet die bestehende VACD-Konvertierung.
- `POST /fhir/vacd/husky/validate`: bestehendes FHIR-Document-Bundle als JSON;
  unveraenderte Pruefung ohne Stabilisierung oder Anreicherung.

Beide rufen ausschliesslich den internen Offline-Husky-Instance-Validator auf.
Erzwingt das Immunization-Administration-Dokumentprofil **CH-VACD 6.0.0**
und prueft zusaetzlich deklarierte Profile. CH Core 6.0.0, CH Term 3.3.0,
HL7 Terminology 7.0.1 und Extensions R4 5.2.0 sind lokal geladen.
Unbekannte deklarierte Profile sind Fehler; keine Downloads oder externen
Terminologieaufrufe im Request.

Antwort: originales `OperationOutcome`, HTTP 200 ohne error/fatal,
422 bei Profilfehlern, 400 bei falscher Eingabe, 502 bei Engine-Ausfall.
Maximal 5 MiB FHIR-JSON; keine Speicherung, kein Zielkontakt und keine
klinische Impfempfehlung. Der Validator liest keine Patienten aus HAPI;
der CDA-Weg behaelt den bestehenden read-only Patienten-/Referenzabgleich
der Konvertierung bei.
Die beiden neuen Werkbankaktionen sind eigenstaendige zusaetzliche Prueflaeufe,
nicht automatisch mit HAPI kombiniert. `/cda/vacd/validate` sowie beide
HAPI-Pruefungen des Versands bleiben unveraendert. Kein BridgeLink-Redeploy.

✅ **Im Testlab getestet und freigegeben (2026-11-04):**

| Use Case | Endpunkt | Ergebnis |
|---|---|---|
| CDA Convert | `POST /v1/cda/convert` | Transaction-Bundle, kein Write |
| CDA Import | `POST /v1/cda/import` | HAPI `transaction-response` |
| EchoSOS Import | `POST /v1/echosos/resolve` | HAPI `transaction-response` |
| eMediplan JSON / CHMED16A Convert | `POST /v1/emediplan/convert` | Collection-Bundle, kein Write |
| eMediplan JSON Import | `POST /v1/emediplan/import` | HAPI `transaction-response` |
| eMediplan PDF/QR Convert | Middleware `POST /emediplan/qr/convert` | Collection-Bundle, kein Write |
| eMediplan PDF/QR Import | Middleware `POST /emediplan/qr/import` -> BridgeLink | HAPI `transaction-response` |

CDA wird extern als XML-Raw-Body mit
`Content-Type: application/xml; charset=UTF-8` gesendet. Die API-Werkbank
sendet auch ausgewaehlte CDA-Dateien als Raw-Body, nicht als Multipart.

eMediplan-Wiederimporte sowie Pharmacode-/GTIN- und lokale Refdata-Anreicherung
wurden anhand gespeicherter Ressourcen geprueft. Der Freigabestand ist eine
Testlab-Abnahme, keine pauschale Bestaetigung aller Profile und Fehlerfaelle.

### Dispatcher und Werkbank: aktueller Stand

Der gespeicherte Channel-Stand entspricht funktional dem neuesten Export
Revision 114. OL_CORE und OL_ROUTING sind
importiert, zugewiesen und deployt; die bestehende JWT-Library bleibt erhalten.
Nach dem Refactoring wurden CDA Convert (200/transaction), eMediplan Convert
(200/collection), unbekannter Endpunkt (404/OperationOutcome) und PDF-/QR-Import
(200/transaction-response) geprueft. Nach der CORS-Korrektur bestanden
41 fokussierte Node-Tests.

Browser-CORS ist jetzt im Channel behandelt: erlaubte OPTIONS werden lokal
mit 204 beantwortet, ohne Middleware-/HAPI-Aufruf. Die Antwortheader erlauben
genau `https://middleware.local.omnilink.ch` und Authorization/Content-Type/Accept.
Echte Requests bleiben JWT-geschuetzt. Live bestaetigt sind der oeffentliche
Preflight mit CORS-Headern und ein authentifizierter Browser-CDA-Convert
(200/transaction, kein HAPI-Write). Nicht jede Gateway-Route ist damit neu
abgenommen. Ein Docker-Neustart ist fuer Channel-Aenderungen nicht erforderlich.

VACD Convert bleibt eingerichtet. Der VACD-HAPI-Import ist serverseitig
deaktiviert: `/cda/vacd/prepare` und `/cda/vacd/import` liefern HTTP 410
mit OperationOutcome. Der bestehende BridgeLink-Importpfad laeuft dadurch
in einen Fehler ohne HAPI-Write. Der separate externe VACD-Versand ist
jetzt durch verpflichtende interne CH-VACD-Validierung abgesichert;
ein echter externer Live-Versand bleibt nicht abgenommen.
Die Werkbank verbirgt interne Middleware-Pfade in der Anzeige; Browser-
Netzwerkdetails und originale FHIR-Antworten bleiben davon unberuehrt.

Versionierter Export, Templates und Git-Sync fuer beide Remotes:
[BridgeLink](bridgelink/README.md). Anzeige und Abnahmegrenzen:
[Werkbank](TEST-CLIENT.md).

### Epic JWKS

Die Middleware stellt `GET /.well-known/jwks.json` bereit. BridgeLink bildet
`GET https://api.omnilink.ch/v1/.well-known/jwks.json` ohne Authentifizierung
auf diese Route ab. Die separate GET-Destination umgeht die FHIR-Verarbeitung;
Destination 99 reicht den JWKS-Body und HTTP-Status unveraendert weiter.

Compose bindet nur den oeffentlichen RSA-Schluessel read-only unter
`/run/epic/epic-public.pem` ein und setzt `EPIC_PUBLIC_KEY_PATH` entsprechend.
Die Host-Datei liegt standardmaessig unter
`/home/ansibleadmin/.local/share/omnilink/epic/epic-public.pem`.
Bei anderen Installationen vor dem Start `EPIC_PUBLIC_KEY_HOST_PATH` auf den
absoluten Host-Pfad setzen; die Datei muss bereits existieren.
`EPIC_JWKS_KID` ist standardmaessig `epic-key-1` und muss dem `kid` im
JWT-Header entsprechen.

Das zugehoerige `epic-private.pem` liegt im selben geschuetzten Host-Verzeichnis
(Verzeichnisrechte `700`, Dateirechte `600`), ausserhalb des Repositorys und
Docker-Build-Kontexts. Es wird nicht in die Middleware eingebunden.
Den privaten Schluessel sicher sichern und nur dem spaeteren JWT-Signierer
zugaenglich machen. Das Bereitstellen des JWKS implementiert noch keinen
JWT-Signierablauf.

Der Endpoint antwortet bei fehlender oder ungueltiger Schluesselkonfiguration
mit HTTP `503`, ansonsten mit HTTP `200` und einem RSA-JWKS fuer `RS256`.
Bei einem Schluesselwechsel den neuen oeffentlichen Schluessel und eine neue
`kid` koordiniert mit dem Signierer ausrollen; das aktuelle JWKS enthaelt nur
einen Schluessel und bietet noch keine Ueberlappungsphase fuer Rotation.

✅ **EchoSOS erfolgreich getestet am 2026-10-21:**
`POST https://api.omnilink.ch/v1/echosos/resolve`
liefert nach dem HAPI-Write HTTP `200 OK` mit einem FHIR-Bundle vom Typ
`transaction-response`. Details siehe Abschnitt „EchoSOS ueber BridgeLink“.

🚧 **Weitere, oben nicht aufgefuehrte Gateway-Use-Cases:** noch nicht freigegeben.

### Bruno / aktueller BridgeLink-Aufruf

Für Bruno wird der externe BridgeLink-CDA-Endpunkt verwendet:

```text
https://api.omnilink.ch/v1/cda/import
```

Import-Aufruf:

```text
POST https://api.omnilink.ch/v1/cda/import
```

Der interne FastAPI-Pfad `/cda/import` ist ein authentifizierter Proxy zu
BridgeLink und gibt dessen Importantwort zurueck, nicht das vorbereitete Bundle.

Seit der Trennung von Convert und Import gilt:

- `POST /cda/convert` konvertiert und validiert nur; er schreibt nicht nach HAPI.
  Die ID-Aufloesung fuer Patient/Practitioner/Organization erfolgt read-only
  (GET auf HAPI); fehlende Ressourcen erhalten eine lokal vergebene ID und
  werden als Bundle-Eintraege mitgeliefert, sodass sie erst beim Import
  entstehen.
- `POST /cda/import` ist ein Proxy: Er leitet CDA-Body und Keycloak-Bearer-Token
  an BridgeLink weiter, und BridgeLink schreibt das Bundle nach HAPI FHIR.
  Das Ziel ist per `BRIDGELINK_CDA_IMPORT_URL` konfigurierbar; seit 2026-10-30
  zeigt es auf `https://api.omnilink.ch/v1/cda/import`.

Auch extern ist die Trennung seit 2026-10-30 vollzogen (BridgeLink-Dispatcher,
`responseTarget`-Flag):

- `POST https://api.omnilink.ch/v1/cda/convert` -> nur Konvertierung, Antwort
  ist das Transaction-Bundle (`"type": "transaction"`), kein HAPI-Write.
- `POST https://api.omnilink.ch/v1/cda/import` -> Konvertierung + HAPI-Write,
  Antwort ist die HAPI-Quittung (`"type": "transaction-response"`).

Fuer einen Write den externen Import-Endpunkt `/v1/cda/import` verwenden;
`/v1/cda/convert` schreibt nicht nach HAPI.

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

In der API-Werkbank sind CDA-Convert/-Import, eMediplan-JSON/CHMED16A-
Convert/-Import, eMediplan-FHIR-JSON-Import, PDF/QR-Convert/-Import,
EchoSOS-URL-Import und Patient `$everything` freigeschaltet.
Text-/JSON-eMediplan-Aufrufe nutzen die BridgeLink-Routen; PDF/QR-Dateien
nutzen die bestehenden Same-Origin-Middleware-Endpunkte, beim Import mit
anschliessendem BridgeLink-Write. Nicht implementierte Gateway-Routen bleiben
ausgeblendet. Alle Requests verwenden den aktiven Keycloak-Bearer-Token.

```text
https://middleware.local.omnilink.ch/echosos-fhir-test.html
https://middleware.local.omnilink.ch/fhir-query-client.html
https://middleware.local.omnilink.ch/epic-spital-emediplan-cda.html
https://middleware.local.omnilink.ch/card-analysis-test.html
```

Der separate eRezept & eMediplan Reader unter
`https://middleware.local.omnilink.ch/erezept-emediplan-reader.html` liest QR-Codes aus PDFs
und Bildern lokal im Browser. Er benoetigt keine Anmeldung und laedt keine
Dokumente hoch. Originales CHMED16A1-JSON kann lokal angezeigt und
heruntergeladen werden. Nur nach Klick auf "FHIR-JSON konvertieren" sendet er
das dekodierte JSON an `POST /emediplan/convert`; dessen bestehender Workflow
kann Terminologie-/Refdata-Dienste nutzen. Das FHIR-Bundle wird angezeigt und
zum Download angeboten, ohne Import oder HAPI-Schreibzugriff.
Decoder-Bibliotheken werden von jsDelivr geladen.
Die bisherigen Pfade `/qr-reader.html` und `/erezept-reader.html` bleiben als Aliase verfuegbar.
Sichtbare QR-Inhalte und unsichtbare PDF-Metadaten-Links erhalten getrennte,
farblich gekennzeichnete Ueberschriften. Ein abweichender Metadaten-Link ist
keine Bestaetigung der Rezeptgueltigkeit.

Die Clients unterstützen Keycloak Authorization Code mit PKCE `S256`.
Issuer: `https://idp.omnilink.ch/realms/omnilink`. Der API-Werkbank- und
EchoSOS-Client verwenden die verborgen vorbelegte öffentliche Client-ID
`app-omnilink-cardtest`; ein Client Secret wird im Browser nicht verwendet.
Die jeweilige Redirect-URI, zum Beispiel
`https://middleware.local.omnilink.ch/test-client.html`, muss im Keycloak-Client freigeschaltet sein.

Der CDA-Import der API-Werkbank verlangt einen Keycloak-Bearer-Token. Der
Same-Origin-Proxy `POST /cda/import` (ebenso der ältere Alias
`POST /_proxy/bridge/cda`) leitet CDA-Body und Bearer-Token an
BridgeLink weiter (aktuell `POST https://api.omnilink.ch/v1/cda/import`).

Das bedeutet: Die Root-URLs selbst sind nicht öffentlich erreichbar und müssen mit gültigen Zugangsdaten aufgerufen werden.

---

## 1) FHIR ueber BridgeLink: https://fhir.local.omnilink.ch/fhir/

Dieser Basis-Endpunkt ist der FHIR REST-API-Basispfad. Erwartet wird:

- Authentifizierung und Berechtigung durch BridgeLink
- FHIR-typische REST-Aufrufe wie z. B.:
  - `GET /fhir/Patient/...`
  - `GET /fhir/Observation/...`
  - `POST /fhir/ResourceType`
  - `PUT /fhir/ResourceType/id`
  - `PATCH /fhir/ResourceType/id`
  - `DELETE /fhir/ResourceType/id`
  - `GET /fhir/metadata`

### Erwartetes Verhalten

- Wenn keine Anmeldung vorliegt: `401 Unauthorized`
- Wenn gültig authentifiziert: FHIR-JSON-Antworten im Standardformat
- Typische Antwortformate:
  - `application/fhir+json`
  - `Content-Type: application/fhir+json`

### Beispiel

```http
GET https://fhir.local.omnilink.ch/fhir/Patient
Authorization: Bearer <JWT>
Accept: application/fhir+json
```

Erwartung:

- Erfolgreich: FHIR-Bundle mit Patient-Ressourcen
- Fehler: `404`, `400`, `401`, `500` je nach Resource und Anfrage

---

## 2) CDA ueber BridgeLink: Convert und Import

Die externen CDA-Endpunkte liegen unter `/v1/cda/convert` und `/v1/cda/import`,
nicht auf dem FHIR-Server selbst.

### Erwartetes Verhalten

- Ohne gueltige BridgeLink-Authentifizierung: `401 Unauthorized`
- Mit gueltigem JWT und Berechtigung: Zugriff auf die freigegebenen Middleware-Endpunkte

### Aktueller Standardfluss

Der derzeitige Arbeitsweg ist:

- CDA wird fuer den Import extern per `POST https://api.omnilink.ch/v1/cda/import` an
  BridgeLink gesendet und an die interne Middleware-Route weitergeleitet
- Die Middleware wandelt das CDA in ein FHIR Bundle mit einer CH IPS Composition um. Die
  klinischen Ressourcen werden in den zugehörigen Composition-Sections referenziert.
- Import-Bundles ergänzen für FHIR-DomainResources eine generierte `Narrative`
  (`resource.text`), sofern die Ressource noch keine Narrative enthält. Ausgenommen
  sind Nicht-DomainResources wie `Bundle`, `Binary` und `Parameters`.
- Das Bundle wird an BridgeLink zur Weiterleitung an den FHIR-Server zurückgegeben
- BridgeLink schreibt das Bundle an den FHIR-Server und gibt dessen Ergebnis an den Client zurück

Die Python-Middleware selbst verwendet intern die Route `/cda/...`. Der externe
BridgeLink-CDA-Import-Endpunkt ist
`https://api.omnilink.ch/v1/cda/import`. Convert nutzt dieselbe Konvertierung,
setzt aber `responseTarget=none` und liefert das Bundle ohne Write. Die internen Middleware-Routen
bleiben unveraendert; der externe Pfad ist keine zusaetzliche FastAPI-Route.

Das ist der relevante Produktionsfluss, wenn wir Daten in den FHIR-Server importieren wollen.

### Typische Middleware-Endpunkte

| Methode | Pfad | Verhalten | Zweck |
|---|---|---|---|
| `GET` | `/health` | Liefert den technischen Health-Status | Betrieb/Monitoring |
| `GET` | `/metadata` | Liefert CapabilityStatement im Debug-Modus | FHIR-Metadaten |
| `POST` | `/cda/debug` | Parst CDA und liefert Profil, Patient, Header und Sections | CDA-Diagnose |
| `POST` | `/cda/convert` | Konvertiert CDA in ein FHIR-Bundle | CDA -> FHIR |
| `POST` | `/cda/validate` | Konvertiert CDA und validiert intern ohne Speicherung; `bundle_type=transaction` oder `document` | CDA -> FHIR -> HAPI `$validate` |
| `POST` | `/fhir/validate` | Validiert ein vorhandenes FHIR-Bundle gegen deklarierte Profile, ohne Speicherung | FHIR -> HAPI `$validate` |
| `POST` | `/cda/import` | Proxy: leitet CDA mit Bearer-Token an BridgeLink; BridgeLink schreibt nach HAPI | CDA -> BridgeLink -> HAPI |
| `POST` | `/cda/etoc/convert` | Erzeugt ein CH-eTOC-Dokumentbundle | CDA -> CH-eTOC |
| `POST` | `/cda/umzh/convert` | Erzeugt ein UMZH-FHIR-Bundle | CDA -> UMZH |
| `POST` | `/cda/umzh/send` | Konvertiert CDA und versendet den UMZH-Workflow | UMZH-Sendefluss |
| `POST` | `/cda/vacd/convert` | Erzeugt ein CH-VACD-Dokumentbundle | CDA -> CH-VACD |
| `POST` | `/cda/vacd/validate` | Konvertiert und validiert das CH-VACD-Dokument ohne Speicherung | CDA -> CH-VACD -> HAPI `$validate` |
| `POST` | `/cda/vacd/husky/validate` | Zusaetzliche Offline-Profilpruefung mit Husky | CDA -> CH-VACD 6.0.0 -> Husky |
| `POST` | `/fhir/vacd/husky/validate` | Bestehendes VACD-Document unveraendert mit Husky pruefen | FHIR-JSON -> Husky |
| `POST` | `/cda/vacd/prepare`, `/cda/vacd/import` | Deaktiviert, HTTP 410 mit OperationOutcome | Kein Import |
| `POST` | `/cda/vacd/send` | Konvertiert CDA und versendet an den VACD-Zielserver | CH-VACD-Sendefluss |
| `POST` | `/emediplan/convert` | Konvertiert Text, PDF oder QR-Bild in ein FHIR-Bundle | eMediplan -> FHIR |
| `POST` | `/emediplan/validate` | Konvertiert eMediplan-Daten (Text, PDF oder QR-Bild) und prueft das Bundle beratend gegen deklarierte Profile plus striktes CH-EMED-MedicationStatement; keine Speicherung | eMediplan -> FHIR -> HAPI `$validate` |
| `POST` | `/emediplan/prepare` | Bereitet eMediplan oder FHIR-JSON mit Importpruefungen als Transaction-Bundle vor; kein Write | BridgeLink -> Middleware -> BridgeLink |
| `POST` | `/cda/prepare` | CDA-Transaction fuer Import vorbereiten; Medikationen verpflichtend mit HAPI pruefen | Kein Write; CDA-Gateway-Routingupdate erforderlich |
| `POST` | `/emediplan/import` | Konvertiert eMediplan-Daten und importiert das FHIR-Bundle über BridgeLink | eMediplan -> FHIR -> BridgeLink -> HAPI |
| `POST` | `/emediplan/import-bundle` | Validiert ein FHIR-Resource-Objekt oder Bundle und importiert es über BridgeLink | FHIR-JSON -> BridgeLink -> HAPI |
| `POST` | `/emediplan/qr/convert` | Liest einen eMediplan-QR-Code und konvertiert ihn | eMediplan-QR -> FHIR |
| `POST` | `/emediplan/qr/import` | Liest einen eMediplan-QR-Code, konvertiert und importiert über BridgeLink | eMediplan-QR -> FHIR -> BridgeLink -> HAPI |
| `POST` | `/emediplan/epic-cda` | Konvertiert eMediplan-Daten in Epic-CDA-XML | eMediplan -> Epic CDA |
| `POST` | `/fhir/medications/epic-cda` | Konvertiert ein FHIR-Bundle in Epic-CDA-XML | FHIR -> Epic CDA |
| `GET` | `/fhir/medications/epic-cda/from-server` | Liest Medikamente aus FHIR und liefert Epic-CDA-XML | FHIR -> Epic CDA |
| `POST` | `/hl7v2/convert` | Konvertiert ORU^R01 in ein FHIR-Bundle | HL7v2 -> FHIR |
| `POST` | `/hl7v2/import` | Konvertiert ORU^R01 und importiert das Bundle | HL7v2 -> BridgeLink -> HAPI |
| `POST` | `/echosos/qr` | Dekodiert EchoSOS-QR/PKPass und liefert ein Transaction-Bundle; BridgeLink schreibt nach HAPI | EchoSOS -> BridgeLink -> HAPI |
| `POST` | `/fhir/stabilize` | Stabilisiert ein FHIR-Resource-Objekt oder Bundle | FHIR-Importvorbereitung |
| `POST` | `/fhir/convert` | Stabilisiert, validiert und verarbeitet ein FHIR-Bundle | FHIR-Import |
| `POST` | `/terminology/{resource_type}/{operation}` | Leitet Terminologieoperationen an TX weiter | Terminologie |

### eMediplan-Import ueber BridgeLink

Der externe BridgeLink-Endpunkt `POST /v1/emediplan/import` muss auf
`https://middleware.local.omnilink.ch/emediplan/prepare` routen und
`responseTarget=hapi` setzen. Dieser Middleware-Endpunkt nimmt CHMED16A-Text,
eMediplan-JSON, PDF/QR-Bilder oder FHIR-JSON entgegen. Er verlangt einen
Bearer-Header, fuehrt die gemeinsamen Importpruefungen aus und liefert ein
Transaction-Bundle zurueck, ohne BridgeLink aufzurufen oder nach HAPI zu schreiben.
Destination 02 in BridgeLink fuehrt den anschliessenden HAPI-Write aus.
Der HTTP Sender muss den zum Eingang passenden Content-Type weitergeben
(z.B. `application/json`, `text/plain`, `application/pdf` oder `image/png`).
`/fhir/convert` ist fuer eMediplan-Rohdaten ungeeignet; `/emediplan/import`
als Rueckrufziel wuerde eine Schleife erzeugen.

#### BridgeLink-Konfiguration

- Source Transformer: `/v1/emediplan/convert` -> `/emediplan/convert` mit
  `responseTarget=none`; `/v1/emediplan/import` -> `/emediplan/prepare` mit
  `responseTarget=hapi`.
- Der Header-Container im Source ist ein `MessageHeaders`-Objekt.
  Authorization mit `sourceMap.get('headers').getHeader('Authorization')`
  auslesen, nicht mit `keySet()` oder einer Java-Map-Iteration.
- Den Originalwert in `channelMap` als `middlewareAuthorization` ablegen.
  Destination 01 HTTP Sender: Header-Tabelle `Authorization` =
  `${middlewareAuthorization}`. Der Wert enthaelt bereits `Bearer`.
  Die erfolgreiche JWT-Pruefung am HTTP Listener allein leitet keinen
  Header weiter. Tokens weder fest hinterlegen noch loggen.
- Destination 01 laeuft nur fuer POST. Sie speichert `middlewareResponse`
  und den HTTP-Sender-Status aus `connectorMap.get('responseStatusCode')`
  als `middlewareStatusCode`. Nur erfolgreiche, schreibbare Bundles werden
  als `fhirJson` freigegeben; Fehler setzen `gatewayError` und
  `gatewayErrorStatusCode`.
- Destination 02 schreibt nur bei POST, `responseTarget=hapi`, ohne
  `gatewayError` und mit nicht leerem `fhirJson`. Die Antwort wird als
  `finalResponse`, der Connector-HTTP-Status als `hapiStatusCode` gespeichert.
- Destination 10 verarbeitet JWKS-GET separat. Destination 99 wartet auf
  die vorherigen Destinations und gibt Body und Status des jeweiligen
  Upstreams zurueck. Bei erwartetem HAPI-Write darf sie nicht auf das
  vorbereitete Middleware-Bundle als Erfolg zurueckfallen. Fehlende
  HAPI-Antwort oder fehlender HTTP-Status fuehren zu `502`.
- HTTP Listener: Response = `99 Response`, Response Code =
  `${responseStatusCode}`. Nach Channel-Aenderungen speichern und redeployen.

JSON- und PDF-/QR-Import inklusive Wiederimport wurden am 2026-11-04 im
Testlab geprueft. Details und Grenzen der Abnahme:
[TEST-CLIENT.md](TEST-CLIENT.md#emediplan-abnahme-2026-11-04).

`POST /emediplan/import` konvertiert Text/PDF-eMediplan-Daten in der Middleware,
validiert das FHIR-Transaction-Bundle und sendet das FHIR-JSON mit dem
Keycloak-Bearer-Token an BridgeLink. `POST /emediplan/qr/import` liest
zunaechst den QR-Code aus dem PDF/Bild und nutzt denselben Importpfad.
Der QR-Inhalt wird gemaess dem offiziellen
[CHMED16A-Datenmodell](https://github.com/ig-emediplan/specification/tree/main/chmed16a)
und [ChTransmissionFormat](https://github.com/ig-emediplan/specification/tree/main/chtransmissionformat)
als `CHMED16A0` (un-komprimiertes JSON) oder `CHMED16A1` (Base64-kodiertes
GZIP-JSON) verarbeitet. Andere CHMED-Versionen werden hier nicht als
CHMED16A interpretiert.
`POST /emediplan/import-bundle` nimmt stattdessen ein fertiges FHIR-Resource-
Objekt oder Bundle entgegen, validiert es und sendet es ebenfalls als
`application/fhir+json` an BridgeLink.

Die Import-URL ist ueber `BRIDGELINK_EMEDIPLAN_IMPORT_URL` konfigurierbar und
standardmaessig `https://api.omnilink.ch/v1/emediplan/import`. Der BridgeLink-
Channel muss FHIR-JSON annehmen, den Write nach HAPI ausfuehren und die
Transaction-Antwort zurueckgeben. Die Middleware gibt BridgeLink-HTTP-Status,
Body und relevante Antwortheader unveraendert weiter. `/emediplan/convert`
und `/emediplan/qr/convert` bleiben reine Konvertierungsendpunkte ohne Write.

Vor jedem eMediplan-Write stabilisiert die Middleware das Bundle und entfernt
in-Bundle-Duplikate. Patientinnen und Patienten werden auf dem Ziel-FHIR-Server
zuerst per Identifier und ersatzweise per exakt abgeglichenem Namen und
Geburtsdatum gesucht. Ein bereits vorhandener Patient wird nicht erneut
geschrieben; Referenzen werden auf dessen FHIR-ID umgestellt. Medication,
MedicationStatement und Practitioner werden ebenfalls per Identifier
abgeglichen und bei einem Treffer unter der bestehenden FHIR-ID aktualisiert.
Mehrdeutige Treffer brechen mit HTTP `409` ab; nicht erreichbare FHIR-Patienten-
oder Identifier-Suchen brechen mit HTTP `502` ab.

Pharmacode und GTIN werden gegen die mit der Middleware ausgelieferten
Swissmedic-Zuordnungsdateien abgeglichen. Bekannte Pharmacodes erhalten die
zugehörige GTIN-Codierung und verfuegbare Produktdaten. Practitioner-GLNs werden
validiert und best-effort mit Refdata-Name und -Adresse angereichert. Diese
Abgleiche laufen auch beim Import eines bereits bestehenden FHIR-JSON-Bundles;
der Terminology-Service validiert zusaetzlich die von ihm unterstuetzten Codes.

### EchoSOS ueber BridgeLink

| Zugriff | Methode | URL | Antwort |
|---|---|---|---|
| Extern ueber BridgeLink | `POST` | `https://api.omnilink.ch/v1/echosos/resolve` | HAPI-Ergebnis als FHIR-Bundle mit `type: transaction-response` |
| Browser-Import ueber Same-Origin-Proxy | `POST` | `/echosos/import` | Leitet den authentifizierten Request an den festen BridgeLink-Endpunkt weiter |
| Lokale QR-Vorschau | `POST` | `/echosos/preview` | Dekodiert rohe URL-, Bild- oder PKPass-Daten mit Bearer-Header; alle erkannten Felder, kein BridgeLink-/FHIR-Zugriff und kein Write |
| Direkt an die Middleware | `POST` | `https://middleware.local.omnilink.ch/echosos/qr` | FHIR-Bundle mit `type: transaction`, noch ohne Write |
| Same-Origin-FHIR-Leseproxy | `GET` | `/echosos/fhir/Patient`, `/echosos/fhir/Patient/{id}` oder `/echosos/fhir/Patient/{id}/$everything` | Leitet authentifizierte Patient-Lesezugriffe an `FHIR_BASE` weiter |

Die Middleware dekodiert den EchoSOS-QR beziehungsweise die PKPass-Datei,
gleicht den Patienten ab und erstellt das Transaction-Bundle. BridgeLink
schreibt dieses Bundle nach HAPI und gibt die Transaction-Antwort zurueck.
Der externe Pfad ist keine zusaetzliche FastAPI-Route.

Seit 2026-10-29 sendet der Browser Bild-/PKPass-Dateien nur an die lokale
Vorschau `/echosos/preview`. Fuer den anschliessenden Import ueber
`/echosos/import` und BridgeLink verwendet er ausschliesslich den geprueften
`source_url`-EchoSOS-Link als `text/plain; charset=utf-8`.
Neue EchoSOS-Allergieangaben werden als `unconfirmed` mit dem Patienten als
`asserter` angelegt; vorhandene Bewertungen bleiben beim Wiederimport erhalten.

**Bestaetigter Aufruf vom 2026-10-21:**

- HTTP `200 OK`, beobachtete Laufzeit ca. `2176 ms`
- `Content-Type: application/json;charset=utf-8`
- `resourceType: Bundle`, `type: transaction-response`
- Patient-Eintrag mit `response.status: 200 OK` und
  `response.location: Patient/{id}/_history/{version}`
- `response.etag`, `response.lastModified` und ein informatives
  `OperationOutcome` im Patient-Eintrag

HTTP `200` allein ersetzt nicht die Pruefung der einzelnen
`entry[].response.status` und gegebenenfalls `OperationOutcome`-Issues.
Die Transaction-Antwort ist kein Patientendaten-Bundle. Fuer die Notfallansicht
wird nach erfolgreichem Write separat
`GET /echosos/fhir/Patient/{id}/$everything?_count=500` aufgerufen. Die
Same-Origin-Route leitet die Anfrage mit dem Keycloak-Bearer-Token an den
konfigurierten FHIR-Server weiter. Die Patient-ID kann aus `response.location`
entnommen werden.

`_count=500` ist die Seitengroesse, kein Gesamtlimit. Der Same-Origin-Proxy
fasst vertrauenswuerdige Folgeseiten zusammen und meldet unvollstaendige
Abfragen als Fehler. Die Ansicht zeigt alle Ressourcen und Felder sowie
Impfungen mit Anzahl und Details.

Weitere Details: [EchoSOS zu FHIR](docs/echosos-fhir.md).
Der erfolgreiche API-Test ist vom Browser-Login zu unterscheiden:
Der EchoSOS-Keycloak-Login meldet am 2026-10-21 noch
`Invalid parameter: redirect_uri`. Die gespeicherte Redirect-Freigabe ist
noch nicht verifiziert; siehe
[offener Keycloak-Login](TEST-CLIENT.md#offener-keycloak-login-stand-2026-10-21).

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

`POST /hl7v2/convert` verarbeitet HL7v2-Nachrichten vom Typ `ORU^R01`.
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
  `https://fhir.omnilink.ch/fhir/CodeSystem/hl7v2-local`
- HL7v2-Abweichungskennzeichnungen wie `LL` als FHIR-`interpretation`

LOINC-Codes werden automatisch zentral über TX validiert. Lokale Codes werden
übernommen, aber nicht gegen TX validiert.

`POST /hl7v2/import` verwendet dieselben Eingabeformen und gibt das
erzeugte Transaction-Bundle an BridgeLink zurück. BridgeLink schreibt es an den
FHIR-Server.

Beispiel Raw-Body:

```bash
curl -X POST \
  -H "Content-Type: text/plain" \
  --data-binary @message.hl7 \
  https://fhir.local.omnilink.ch/middleware/hl7v2/convert
```

Beispiel Datei-Upload:

```bash
curl -X POST \
  -F "file=@message.hl7" \
  https://fhir.local.omnilink.ch/middleware/hl7v2/convert
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

- `POST /cda/convert`
- `POST /cda/vacd/convert`
- `POST /emediplan/convert`
- `POST /cda/umzh/convert`

Erwartung:

- `200 OK` mit JSON- oder XML-Ergebnis bei gültigen Inputdaten
- `400 Bad Request` bei fehlendem Input oder ungültigem Format
- `500 Internal Server Error` für interne Fehler

Wichtig: `POST /cda/convert` liefert ein Bundle zurück. BridgeLink kann dieses Bundle als separaten Schritt an den FHIR-Server senden:

```http
POST <FHIR-Server-Route ueber BridgeLink>/fhir
Authorization: Bearer <JWT>
Content-Type: application/fhir+json
Accept: application/fhir+json
```

Das bedeutet: Der Ablauf kann auch so aussehen:

1. `POST /cda/convert` mit CDA-Daten
2. Ergebnis: FHIR Bundle JSON
3. BridgeLink sendet das Bundle an die FHIR-Server-Route

So ist der Convert-Call nicht der eigentliche Import, sondern die Vorstufe fuer den direkten FHIR-Write ueber BridgeLink.

#### 2. BridgeLink-Import-Endpunkte

Beispiele:

- `POST /cda/import`
- `POST /emediplan/import`
- `POST /emediplan/import-bundle`
- `POST /emediplan/qr/import`

Erwartung:

- `200 OK` mit der BridgeLink/FHIR-Transaction-Antwort
- `400 Bad Request` bei ungültigem Input
- Die Middleware validiert das Bundle vor dem BridgeLink-Write. Der HAPI-Status
  und die Entry-Ergebnisse stammen aus der BridgeLink-Transaction-Antwort.

#### 3. Conversion-to-XML-Endpunkte
Diese Endpunkte liefern als Output XML statt JSON.

Beispiele:

- `POST /fhir/medications/epic-cda`
- `POST /emediplan/epic-cda`
- `GET /fhir/medications/epic-cda/from-server`

Erwartung:

- `Content-Type: application/xml`
- `200 OK` bei gültiger Konvertierung
- `400` bei ungültigem Input
- `500` bei internen Exceptions

#### 4. Send-/Workflow-Endpunkte
Diese Endpunkte verarbeiten einen kompletten Workflow mit Konvertierung + Versand.

Beispiele:

- `POST /cda/umzh/send`
- `POST /cda/vacd/send`

Erwartung:

- Rückgabe mit zwei Blöcken:
  - `convert`: Workflow-Informationen
  - `send`: Versandreport / Status des Zielsystems

`POST /cda/vacd/send` richtet sich an einen openEHR-basierten CH-VACD-
Referenzserver (z. B. `https://vaccination-demo.raly.ch/api/fhir`, Default via
`VACD_SEND_BASE_URL`, ueberschreibbar per Query-Parameter `destination_base_url`).
Ablauf:

1. CDA wird wie bei `/cda/vacd/convert` zu einem CH-VACD-Document-Bundle konvertiert.
   Vor jedem Zielkontakt wird das Dokument intern gegen die deklarierten
   CH-VACD-/CH-Core-Profile validiert. `error`/`fatal` blockiert mit HTTP 422
   und OperationOutcome; Validator-Ausfall oder ungueltige Antwort mit HTTP
   502. Es wird in diesen Faellen kein Zielpatient gesucht oder angelegt.
2. Die enthaltene `Patient`-Ressource wird zunaechst beim Zielserver gesucht, um
   Duplikate zu vermeiden (analog zum Find-or-Create-Ablauf gegen den eigenen
   FHIR-Server in `services/patient_service.py`): zuerst per `GET
   {ziel}/Patient?identifier=<system>|<value>` je Identifier der Ressource; lehnt der
   Zielserver diesen Suchparameter ab (z. B. der raly.ch-Demoserver, der nur `name`
   unterstuetzt), erfolgt ein Fallback per `GET {ziel}/Patient?name=<Nachname>`,
   bestaetigt durch exakten Abgleich von Familienname, erstem Vornamen und
   `birthDate`. Mehrdeutige oder widerspruechliche Treffer blockieren mit HTTP 409.
   Fehlerhafte, unvollstaendige oder paginierte Suchantworten blockieren ebenfalls.
   Nur wenn kein Treffer gefunden
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
4. Bei einem bestehenden Patienten werden dessen Impfungen ueber
   `GET {ziel}/Immunization?patient=Patient/<id>` abgeglichen. Vorhandene
   Impfungen werden ausgelassen; widerspruechliche klinische Daten stoppen
   den Versand mit HTTP 409. Ein Teilimport erhaelt neue Dokumentkennungen,
   bereinigte Section-Referenzen und neu erzeugte Impfnarrative.
   Ohne neue Impfungen erfolgt kein Dokument-POST (`send.status=skipped`).
5. Das aktualisierte Bundle wird erneut intern validiert. Nur ohne
   `error`/`fatal` wird genau dieser Payload per `POST {ziel}/Bundle`
   gesendet. Auch ein Ausfall dieser zweiten Pruefung verhindert den
   Dokumentversand. Der Patientenabgleich ist dann bereits erfolgt:
   Ein Zielpatient kann bereits angelegt worden sein; kein automatisches
   Rollback. Die Fehlerantwort weist darauf hin. Bei Profilfehlern zeigt
   `X-VACD-Validation-Phase=before-bundle` diese Phase.

Warnungen allein blockieren nicht. Erfolgreiche Sendeberichte enthalten
beide vollstaendigen OperationOutcomes unter
`send.validation.before_patient` und `send.validation.before_bundle`.
Eine vorherige manuelle Validierung ist kein Freigabetoken: jeder
Sendeaufruf wird erneut geprueft. CH-VACD-Dokumenttyp und Profildeklaration
sind auch bei direktem Aufruf des Sendeservice zwingend.

`send.bundle.http_status` und `.response` enthalten den externen
Dokumentstatus und Antwortbody. `send.patient` weist Ziel-ID und
Wiederverwendung aus; `send.immunizations` zaehlt neue und ausgelassene
Impfungen. Die Werkbank zeigt diese Angaben vor den internen Validierungen.
Ein HTTP 201 mit Document-Bundle bestaetigt den Dokumentaufruf, nicht
separat eine Neuanlage jeder enthaltenen Ressource oder einer openEHR-Composition.

`VACD_IMPORT_DB` (Default `/var/lib/omnilink/vacd/imports.sqlite3`) wird
im Compose-Volume `vacd-import-state` persistiert. Gemeinsames Register
und Dateilocks serialisieren Aufrufe je Ziel. Bereits verarbeitete Quellen
werden ohne neuen Versand ausgewiesen; unklare Schreibausgaenge blockieren
weitere Aufrufe dieses Ziels bis zur manuellen Klaerung.
Der Registerschluessel nutzt die urspruengliche Quellkennung vor der
VACD-UUID-Erzeugung. Ein zusaetzlicher CDA-Inhaltshash-Abgleich erkennt
identische erfolgreich verarbeitete Quellen aus aelteren Registereintraegen.
Klinische Konfliktmeldungen nennen das abweichende Feld, ohne Werte offenzulegen.
Details und Bruno-Lesepruefung:
[CH-VACD-Ablauf](docs/ch-vacd-immunization-administration.md).

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
  -X POST "https://fhir.local.omnilink.ch/fhir" \
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
POST https://api.omnilink.ch/v1/cda/import
Authorization: Bearer <JWT>
Content-Type: application/xml; charset=UTF-8
```

Erwartung:

- `200 OK` mit Import-Status, falls das CDA valid ist und der FHIR-Server akzeptiert
- `400 Bad Request` bei ungültigem XML oder fehlenden Input
- `500 Internal Server Error` bei internen Fehlern
- `502`/Fehler aus dem FHIR-Server, falls der Import dort fehlschlägt

---

## Allgemeine Regeln

- Die geschuetzten API-Aufrufe verwenden Keycloak-Bearer-Authentifizierung.
  Der separate Epic-JWKS-Abruf ist ohne Anmeldung vorgesehen.
- Das FHIR-Backend erwartet FHIR-konforme Payloads mit `application/fhir+json`.
- Die Middleware erwartet typischerweise XML- oder JSON-Inputs je nach Route.
- Die Root-URLs selbst liefern ohne gültige Authentifizierung nur 401.

## Kurzfassung

- `https://fhir.local.omnilink.ch/fhir/` = FHIR-Route ueber BridgeLink mit GET, POST, PUT, PATCH und DELETE
- `https://api.omnilink.ch/v1/cda/convert` = CDA-Konvertierung ohne Write
- `https://api.omnilink.ch/v1/cda/import` = CDA-Import mit HAPI-Write
- `https://api.omnilink.ch/v1/emediplan/convert` = eMediplan-Konvertierung ohne Write
- `https://api.omnilink.ch/v1/emediplan/import` = eMediplan-Import ueber Middleware-Vorbereitung und HAPI-Write
