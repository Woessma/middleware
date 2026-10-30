# BridgeLink: CDA-Use-Cases und Channel-Einstellungen

## Geltungsbereich

Seit 2026-10-30 gibt es zwei externe CDA-Endpunkte (Channel `api_route_dispatcher`
mit `responseTarget`-Flag im Source Transformer):

- `POST https://api.omnilink.ch/v1/cda/convert` — nur Konvertierung, Antwort
  ist das Transaction-Bundle, kein HAPI-Write.
- `POST https://api.omnilink.ch/v1/cda/import` — Konvertierung plus HAPI-Write,
  Antwort ist die HAPI-`transaction-response`.

Port `8081` ist ein interner BridgeLink-Port und keine externe CDA-URL. Die
Middleware-Routen `/cda/...` sind interne Ziele, keine weiteren oeffentlichen
BridgeLink-Endpunkte. Ein Eintrag in dieser Uebersicht bedeutet **nicht**, dass
der betreffende Use-Case bereits als BridgeLink-Channel freigeschaltet ist.

**Belegter Ist-Stand:** Der Channel `API_to_FHIR_MW_CDA_Convert` nimmt Requests am
externen CDA-Endpunkt entgegen. Am 29.09.2026 um 08:14 UTC wurde `api-mwo01`
akzeptiert; die Middleware antwortete auf `POST /cda/convert` mit HTTP 200 und
HAPI protokollierte danach eine BridgeLink-`transaction`. Ein frueherer Request
mit demselben Client wurde noch mit `Client nicht erlaubt` abgewiesen. Die live
aktive Ziel-URL, Auth-Header der Sender, Response-Transformer-Einstellungen und
der endgueltige HAPI-Importstatus sind hier nicht verifiziert. Alte Werte aus
Derby-Dateien sind kein Nachweis fuer die aktive Channel-Konfiguration.

## Encoding-Abnahme vom 2026-10-21

Die bereitgestellte Original-CDA-Datei war gueltiges UTF-8 mit korrekter
XML-Deklaration und Umlauten. Direkte HTTP-Konvertierung an `/cda/convert`
lieferte HTTP 200 und korrektes UTF-8-FHIR-JSON, ohne anschliessenden HAPI-Write.
Im produktiven Importweg wurden zunaechst beschaedigte Umlaute gespeichert.
Nach Korrektur des Bruno-Raw-XML-Headers auf
`Content-Type: application/xml; charset=UTF-8` war der gespeicherte Name korrekt;
auch die sieben Impfungen und insgesamt 20 `$everything`-Ressourcen wurden
lesend verifiziert.

Die explizite Charset-Angabe fuer Raw XML beibehalten. Bei Multipart-Dateien
hingegen den automatisch erzeugten `multipart/form-data; boundary=...`-Header
unveraendert lassen. Keine pauschale Latin-1/UTF-8-Reparatur auf bereits
decodierten Strings anwenden. Eine entfernte XML-Deklaration allein beweist
keinen Encodingfehler. Der exakte interne BridgeLink-Schritt bleibt ohne
Vergleich derselben Nachricht bzw. aktuellen Channel-Export nicht belegt.
Die Management-API war ohne Anmeldung nicht zugaenglich; weder Zugangsdaten
noch produktive Konfiguration wurden fuer diese Diagnose geaendert.

## Gemeinsame Einstellungen (Vorlage, nicht Live-Export)

| BridgeLink-Komponente | Einstellung / Pruefpunkt |
|---|---|
| HTTP Listener | Extern `POST /v1/cda/convert` ueber `https://api.omnilink.ch`; keine weiteren CDA-Pfade oder Port `8081` als externe API dokumentieren. |
| Authenticator | Eingehendes Keycloak-Bearer-JWT pruefen (Signatur, Issuer, Ablaufzeit, erforderliche Realm-Rolle und zugelassener Client). Die Client-Allowlist des Channels muss den tatsaechlichen `azp`/`client_id` enthalten. |
| Request | Raw CDA-XML (`application/xml`) oder Multipart (`multipart/form-data`, Feld `file`) unveraendert mit passendem `Content-Type` inklusive Boundary an die Middleware weitergeben. `/cda/debug` akzeptiert ausschliesslich Multipart. |
| HTTP Sender: Middleware | Internes, vom BridgeLink-Container erreichbares Ziel `POST /cda/<use-case>` konfigurieren. Ziel-URL im aktiven Channel pruefen; weder den Browser-Relay `/_proxy/bridge/cda` noch einen historischen Hostnamen als Ziel uebernehmen. |
| Response | HTTP-Status, `Content-Type` und Laenge des **rohen** Middleware-Bodys erfassen. Nur bei 2xx und erwartetem JSON einen FHIR-Bundle-Body parsen; Fehlerbody und Nicht-2xx unverfaelscht an den Aufrufer weiterreichen. `response.getMessage()` ist allein kein Nachweis fuer einen leeren HTTP-Body. |
| Datenschutz | Weder JWT, komplette Header noch CDA-/FHIR-Payloads protokollieren. Fuer Korrelation Channel, Zeitpunkt, Status, Content-Type und Body-Laenge verwenden. |

Das Bearer-JWT authentifiziert den eingehenden Request; die Middleware-Response
benoetigt kein JWT. Eine nachgelagerte HAPI-Destination hat ihre **eigene**
Authentifizierung. Die genaue interne Middleware-URL und die HAPI-Route muessen
anhand des aktiven Channels verifiziert werden; hier wird keine alte URL als
aktuelle Einstellung ausgegeben.

## Use-Case-Matrix

Alle Zeilen ausser der Standard-Konvertierung **mit nachgelagertem HAPI-Write**
beschreiben moegliche interne BridgeLink-Routen, keine bereits produktiven
externen Schnittstellen. Fuer
weitere oeffentliche Use-Cases ist eine explizite, autorisierte Auswahl innerhalb
des externen `/v1/cda/convert`-Einstiegs erforderlich (z. B. eine serverseitig erlaubte
Use-Case-Kennung). Bis ein solcher Dispatcher eingerichtet und getestet ist,
bleibt der externe Einstieg auf den bisherigen Import beschraenkt.

| CDA-Use-Case | Middleware-Ziel | Eingabe | Middleware-Antwort | BridgeLink-Folgeschritt |
|---|---|---|---|---|
| Diagnose (nur Debug-Modus) | `POST /cda/debug` | Multipart `file` | JSON mit CDA-Diagnose | Kein HAPI-Write; nicht produktiv exponieren (`DEBUG_MODE` erforderlich). |
| Standard-Konvertierung ohne HAPI-Write (extern `/v1/cda/convert`) | `POST /cda/convert` | Raw XML oder Multipart `file` | FHIR-Bundle JSON, standardmaessig `transaction`; optional `bundle_type=document` | `responseTarget='none'`: Bundle direkt an den Client zurueckgeben, kein HAPI-Write. |
| Standard-Import mit HAPI-Write (extern `/v1/cda/import`) | `POST /cda/convert` | Raw XML oder Multipart `file` | FHIR-Bundle JSON (`transaction`) | `responseTarget='hapi'`: Nur bei erfolgreicher Konvertierung das Transaction-Bundle als `application/fhir+json` an HAPI senden; dessen `transaction-response` an den Client geben. |
| CH-VACD-Konvertierung | `POST /cda/vacd/convert` | Raw XML oder Multipart `file` | CH-VACD-Dokumentbundle JSON | Bundle direkt zurueckgeben; kein automatischer HAPI-Write. |
| CH-VACD-Versand | `POST /cda/vacd/send` | Raw XML oder Multipart `file`; Zielkonfiguration erforderlich | JSON mit `convert` und `send` | **Keinen** zusaetzlichen HAPI-/VACD-Sender aktivieren: Die Middleware sendet selbst. Ziel per `VACD_SEND_BASE_URL` oder kontrolliertem `destination_base_url` festlegen. |
| UMZH-Konvertierung | `POST /cda/umzh/convert` | Raw XML oder Multipart `file`; optional `workflow_stage`, `target` | UMZH-FHIR-Bundle JSON | Bundle direkt zurueckgeben; kein automatischer HAPI-Write. |
| UMZH-Versand | `POST /cda/umzh/send` | Raw XML oder Multipart `file`; Zielkonfiguration erforderlich | JSON mit `convert` und `send` | **Keinen** zusaetzlichen HAPI-/UMZH-Sender aktivieren: Die Middleware sendet selbst. Ziel per `UMZH_SEND_BASE_URL` oder kontrolliertem `destination_base_url` festlegen. |
| CH-eTOC-Konvertierung | `POST /cda/etoc/convert` | Raw XML oder Multipart `file`; optional `workflow_stage`, `target` | CH-eTOC-Dokumentbundle JSON | Bundle direkt zurueckgeben; kein automatischer HAPI-Write. |

Bei UMZH und CH-eTOC sind `workflow_stage=initial|updated|completed` und
`target=default|sandbox-placer` zulaessig. Ziel-URLs und
`outbound_authorization` fuer Send-Routen nicht ungeprueft aus externen
Query-Parametern uebernehmen; die Middleware bietet solche Parameter an, aber
die BridgeLink-Konfiguration muss Zielsysteme und Zugangsdaten begrenzen.

## Bestehender Import-Workflow: Abnahme in BridgeLink

1. Externer `POST /v1/cda/convert` mit einem **im Channel erlaubten** Bearer-Client und
   Raw-XML oder Multipart-`file` entgegennehmen. Bei nicht erlaubtem Client
   endet der Request mit 401 vor der Middleware.
2. Den CDA-Body samt passendem Content-Type an die aktive interne
   `POST /cda/convert`-Destination senden. HTTP-Status und Body-Laenge **vor**
   dem Response-Transformer pruefen; bei Nicht-2xx keinen HAPI-Sender ausloesen.
3. Bei 2xx ein valides `Bundle` vom Typ `transaction` erwarten. Erst dieses
   Ergebnis an HAPI senden, mit `Content-Type: application/fhir+json` und der
   fuer HAPI erforderlichen Authentifizierung.
4. Den tatsaechlichen HAPI-HTTP-Status und dessen Antwort an den Client
   weitergeben; einen Middleware-200er nicht als erfolgreichen Import ausgeben.
5. Fuer einen End-to-End-Test `app/tests/data/CDA-EPIC.xml` verwenden, aber nur
   mit bewusst freigegebenem Import: Der externe `/v1/cda/convert`-Workflow schreibt
   danach nach HAPI. Ein isolierter Convert-Test verwendet nur die interne
   Middleware-Route `/cda/convert` oder einen separaten BridgeLink-Testchannel
   ohne HAPI-Destination.

FHIR-zu-Epic-CDA und eMediplan-zu-Epic-CDA sind Ausgabe- bzw. andere
Eingabe-Workflows; sie sind **keine** weiteren oeffentlichen CDA-Importpfade unter
`https://api.omnilink.ch/v1/cda/convert`. Die Middleware-Routen und ihre fachlichen
Vertraege stehen in [ENDPOINTS.md](../ENDPOINTS.md).