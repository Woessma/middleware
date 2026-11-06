# BridgeLink - Project Memory

Stand: 2026-11-06

## Tagesabschluss 2026-11-06: Beratende CH-EMED-Validierung und Mappingfixes

- Neuer advisory Endpunkt `POST /emediplan/validate` (Text/JSON/CHMED16A und
  QR aus PDF/Bild) mit zwei Werkbank-Use-Cases. Die Pruefkopie des
  konvertierten Bundles wird in die CH-EMED-Struktur transformiert
  (contained Medication mit `#`-Referenzen, deterministische
  `urn:uuid`-Identifier, Verschreiber als PractitionerRole) und intern mit
  HAPI gegen deklarierte Profile plus striktes
  `ch-emed-medicationstatement` 6.0.0 geprueft. Realer 6-Medikamente-Plan:
  von 37 auf 0 Fehler. Kein Import, keine Speicherung, keine Blockade.
- Convert-, Prepare- und Importwege liefern bewusst weiterhin die
  CH-Core-Struktur mit eigenstaendigen Medications und
  eMediplan-Identifiern (Basis fuer Upsert/Dedup); die blockierende
  HAPI-Importpruefung bleibt unveraendert scharf und wurde ohne Write
  end-to-end nachgewiesen.
- Echte Mappingfixes aus den Validierungslaeufen: refdata-Practitioner
  erhalten strukturierte `family`/`given`-Namen (ch-pract-1 haette sonst
  Importe blockiert); `dateAsserted` aus Plan-`Dt` mit
  FHIR-dateTime-Guard; `Auth`-GLN als informationSource-Fallback ohne
  `PrscbBy` (gilt auch fuer Convert/Import); GTINs zusaetzlich mit
  CH-EMED-System `urn:oid:2.51.1.1`; generierte Narrative auch im
  Convert-Collection-Bundle.
- Erkenntnisse auf alle Use Cases uebertragen: CDA-Medikationsmapper loest
  eingehende OID-GTINs ueber das Terminologie-Mapping auf und ergaenzt
  GTIN-Zwillingscodings; Dublettenabgleich matcht auch OID-GTIN-Codings;
  refdata-Enrichment setzt keinen text-only-HumanName mehr; EchoSOS-
  Importbundles erhalten Narrative. CDA/VACD/eTOC/UMZH, HL7v2 und PMLC
  waren bereits konform.
- Validierung: 343 Python- und 24 Werkbanktests gruen; mehrfache
  E2E-Pruefungen gegen den internen HAPI (advisory 0 Fehler,
  Importvorbereitung bestanden, dom-6/Slice-Befunde verifiziert beseitigt).
  Bestandsdaten in HAPI werden nicht migriert; Verbesserungen greifen bei
  neuen Importen bzw. Re-Imports per Upsert.
- Middleware mehrfach neu gebaut und deployt, Health jeweils geprueft.
  `main` auf beide Remotes (origin, post) gepusht. Fuer CH-EMED-EPR-konforme
  Ausgaben bleibt der PMLC-Pfad zustaendig.

Details: [ENDPOINTS](../ENDPOINTS.md), [Backlog](backlog.md),
[Roadmap](roadmap.md).

## Tagesabschluss 2026-11-05: Husky, Medikation und Importpruefung

- Interner Husky-3.5.0-Dienst fuer CDA-XSD/Schematron sowie gemeinsame
  Offline-PMLC-/VACD-Profilpruefung deployt. CH-VACD/CH Core 6.0.0,
  keine automatische Uebernahme der Husky-Ballotdefaults.
- PMLC-Vorschau liest nur aktive MedicationStatements, speichert nicht und
  prueft den signierten Werkbank-Client vor dem ersten Patientendatenabruf.
  PDF/A, QR und klinische Reconciliation bleiben offen.
- Import- und Ausgabemapping getrennt: Import behaelt Dupletten-Identifier
  und vorhandene Autoren-/Zeitangaben; EPR-Ausgabe normalisiert enthaltene
  Medication, UUID-Identifier, Provenance und PractitionerRole nur in Kopien.
  Replay des gelieferten Quellbestands: 29 Fehler / 9 Warnungen statt 52 / 10;
  fehlende medizinische Pflichtangaben und PDF/A bleiben echte Fehler.
- Verpflichtende Medikationspruefung am finalen Transaction-Bundle deployt:
  CH-Core-/deklarierte Profile, 422 bei error/fatal, 502 bei Pruefausfall.
  Keine automatische Aenderung bestehender HAPI-Daten.
- **Offen: CDA-Gateway-Redeploy.** Lokale OL_ROUTING-/Channel-Dateien
  verwenden `/cda/prepare` und 180 Sekunden Sender-Timeout. Erst
  Import/Save/Redeploy aktiviert diesen Gateweg im laufenden BridgeLink.
  Die lokal bearbeitete Kopie unter `bridgelink/aktuell/` ist kein
  unveraenderter Liveexport und wird nicht zusaetzlich versioniert.
- Impfstoffmapper erzeugt keine kuenstlichen Swissmedic-Codes und leitet
  aus COVID-Markennamen keine konkrete CVX-Formulierung mehr ab.
  Originalcodes bleiben erhalten. Eindeutige Produktzuordnungen bleiben
  fachlich zu belegen; Warnungen werden nicht pauschal unterdrueckt.
- Werkbank unterscheidet explizite Profilangaben, Ressourcenprofil-Kontext
  und angeforderten Prueflauf, ohne kausale Einzelprofilzuordnung zu erfinden.
  Browserdarstellung mit synthetischer Antwort geprueft.
- Validierung: Import-/Ausgabestand mit 109 Python-, 20 Java- und 54 Node-
  Tests geprueft; anschliessende Impfcode-/Profilkontextkorrektur mit
  36 Python-, 21 Java- und 28 Node-Tests. Synthetischer Live-VACD-Test
  0 Fehler / 6 Warnungen; erfundener Code wird weiterhin mit 422 blockiert.
  Die zuletzt geteilte Original-CDA ist damit nicht erneut abgenommen.
- Middleware und Husky neu gebaut, Health erfolgreich. Beim frueheren
  gleichzeitigen Java-Build/Validatorbetrieb trat Host-OOM mit einem
  HAPI-Neustart auf; HAPI danach gesund, keine weiteren Neustarts.
  Husky vor weiteren Java-Builds stoppen; Maven-Heap auf 256 MiB begrenzt.
- Keine klinischen Writes oder externen VACD-Sends fuer diese Tests.
  Backups, persoenliche Testdateien, Refdata-ZIP, lokale PDF-Deliverables
  und unabhaengige Mapping-Excel-Aenderungen bleiben ausserhalb dieses Commits.

Details: [PMLC](ch-emed-epr-pmlc.md),
[VACD](ch-vacd-immunization-administration.md),
[Husky](../husky-validator/README.md),
[Gateway-Redeploy](../bridgelink/README.md).

## Tagesabschluss 2026-11-02: Reader, Neuaufbau und Refdata

- Reader: `erezept-emediplan-reader.html` ist der kanonische Pfad mit Titel
  "eRezept & eMediplan Reader". `/erezept-reader.html` und `/qr-reader.html`
  bleiben Aliase. PDF-/Bildvorschauen, lokale CHMED16A1-Dekodierung und
  Original-JSON-Download bleiben erhalten; FHIR-Konvertierung erfolgt nur
  auf ausdruecklichen Klick ueber `/emediplan/convert`, ohne Import.
- Sichtbarer QR und unsichtbarer `xmp:signedChmed`-Metadaten-Link werden
  getrennt und farblich beschriftet. Beim untersuchten PDF waren die Links
  unterschiedlich; keiner wird dadurch als gueltig bestaetigt.
  Keine eingebettete externe Rezeptseite und kein automatischer Linkaufruf.
- Lokale PDF-Unterlagen unter `app/tests/data` erstellt:
  `bridgelink-oie-entscheidungsgrundlage.pdf`,
  `omnilink-neubau-migrationskonzept.pdf` (9 Seiten) und
  `omnilink-migration-offene-fragen.pdf` (5 Seiten, F01-F32).
  Letztere verbindet das Konzept mit dem externen Infrastrukturvorschlag.
  Unterlagen sind lokale Deliverables, nicht Bestandteil des Git-Commits.
- Neuaufbau: Middleware behaelt Transformation und Anreicherung, Engine
  Transport/Orchestrierung/Zustellung. OIE wegen geringer Channel-Altlast
  direkt als Zielkandidat pruefen. Rocky/Podman/Quadlets, SELinux, Ansible,
  bestehende Infrastruktur und eigene TLS-Terminierung sind Vorschlaege,
  keine abgeschlossene Umsetzung. Umfang, Jahresangaben 2024, Kosten,
  Support, RPO/RTO und Restore-Nachweise bleiben offen.
- Offizielles Refdata-Partner-ZIP heruntergeladen und Integritaet geprueft;
  NAT/JUR-XML noch nicht importiert. Keine Personendaten oder Downloadkeys
  in die Dokumentation/Git uebernehmen. Offengelegte Keys rotieren.
- Geplant: separate `omnilink_refdata`-Datenbank mit GLN-Index und
  Importer-/Leserrollen auf `postgres.local.omnilink.ch:5433`.
  HAPI-Datenbank `fhir` bleibt unveraendert.
- Benutzer zeigte CloudBeaver unter `https://db-admin.local.omnilink.ch/`
  und eine erfolgreiche rein lesende Rechteabfrage auf `fhir`:
  `rolcreatedb=false`, `rolsuper=false`. Bereitstellung durch einen
  DB-Administrator erforderlich, keine Rechteausweitung der HAPI-Verbindung.
- Nicht umgesetzt: Datenbank-/Rollenerstellung, Refdata-Importer, lokaler
  Lookup oder Ansible-Tasks. Naechster Schritt ist die administrative
  Bereitstellung und danach Datenmodell, Import und Middleware-Anbindung.
- Validierung zum Tagesabschluss: 38 Reader-/EchoSOS-JavaScript-Tests
  erfolgreich, Python-Syntax von `app/main.py` und `git diff --check`
  ohne Fehler.

## Tagesabschluss 2026-10-29: EchoSOS-Import und Darstellung

- Dateieingaben gehen nur noch zur lokalen `/echosos/preview`-Route.
  Anschliessend importiert der Browser den geprueften `source_url`-Link als
  `text/plain; charset=utf-8` ueber BridgeLink, nicht erneut das Bild/PKPass.
  Fehlende oder ungueltige Vorschau-Links verhindern den Import.
- Der Benutzer hat nach der Umstellung einen erfolgreichen Bildimport mit
  anschliessender FHIR-Anzeige gezeigt. Die lokale Vorschau allein ist
  weiterhin keine Speicherbestaetigung.
- Desktop-Layout: Eingabe ein Drittel, FHIR-Visualisierung zwei Drittel.
  Bis 860 Pixel untereinander; fuenf Bildschirmbreiten ohne Seitenueberlauf
  geprueft. Allergietabelle um Reaktionen, Verifizierung, Typ und Kategorien
  erweitert; fehlende Angaben explizit, technische Rohfelder weiterhin sichtbar.
- Neue EchoSOS-Allergien einschliesslich negativer Allergieangaben erhalten
  `unconfirmed` und den Patienten als `asserter`. Bestehende Verifizierung,
  `asserter` und `recorder` bleiben beim Wiederimport erhalten. Der
  EchoSOS-Altbestandsabgleich ignoriert diese Bewertungs-/Quellenfelder,
  damit die Umstellung keine zusaetzlichen Dubletten erzeugt.
- Auf ausdruecklichen Wunsch alle vier aktiven EchoSOS-Allergieeintraege
  anhand ihres Identifier-Systems logisch geloescht. Danach null Treffer und
  HTTP 410 fuer alle vier Ressourcen verifiziert. FHIR-Historie, Patienten
  und andere Ressourcen blieben erhalten. Ein erneuter Import nach dieser
  Loeschung wurde nicht durchgefuehrt.
- Validierung: 14 JavaScript-Clienttests und 40 Python-EchoSOS-Tests erfolgreich.
  Darstellung zusaetzlich im Browser mit synthetischen Daten geprueft.
  Middleware neu gebaut und deployt, Health und ausgelieferten Client geprueft.
- BridgeLink: Authentifizierungsfehler durch nicht definiertes
  `omnilinkJwtAuthenticate()` diagnostiziert; kein Channel-Export im Repository.
  Filter fuer D1/D2 (POST) und JWKS (exakter GET) sowie Destination-99-Antworten
  im Dialog besprochen, aber deren abschliessender Live-Stand ist hier nicht
  versioniert. Fehlerantworten aus D1 duerfen nicht als FHIR-Bundle an D2 gehen;
  Original-HTTP-Fehlerstatus nicht pauschal durch 200 ersetzen.
- Epic-FHIR-GET meldete `insufficient_scope`; unabhaengig vom JWKS-Endpunkt.
  Epic-App-/Scope-Freigaben und separater GET-Workflow bleiben offen.
- Persoenliches Testbild und vorhandene Backup-Datei nicht versionieren.

## Tagesabschluss 2026-10-21: CDA und EchoSOS

- CDA-Zeichencodierung: Originaldatei und direkte HTTP-Konvertierung durch
  `/cda/convert` liefern korrektes UTF-8. Der Importweg mit Bruno lieferte
  zuvor beschaedigte Umlaute. Nach explizitem
  `Content-Type: application/xml; charset=UTF-8` wurde der erneut importierte
  Patient mit korrektem Namen verifiziert. Der genaue interne
  BridgeLink-Decodierungsschritt wurde nicht durch einen Live-Channel-Export
  nachgewiesen; HAPI nicht als Fehlerursache ausgeben. Multipart-Boundaries
  beim Dateiversand beibehalten, nicht durch einen Raw-XML-Header ersetzen.
- Die zwei alten Testpatienten samt 33 zugehoerigen Ressourcen wurden auf
  ausdruecklichen Wunsch logisch geloescht (35 Ressourcen insgesamt).
  Arzt und Organisation sowie FHIR-Historie blieben erhalten.
  Keine Patientennamen, Geburtsdaten oder Original-CDA-Payloads in Git ablegen.
- EchoSOS: feste BridgeLink-Route `/v1/echosos/resolve`, rohe Kamera-/Dateibodies,
  strikte Transaction-Response-Pruefung vor separatem `$everything`.
  Stabile Identifier und klinischer Altbestandsabgleich fuer Blutgruppe,
  Allergien, Probleme und Organspende; Patientenkontakte sind idempotent.
  Bereits vorhandene Dubletten wurden nur nach Freigabe bereinigt.
- Patientenansicht: alle Ressourcentypen und Felder sichtbar, keine
  Encounter-/Beobachtungs-Ausblendungen. Sichere serverseitige Pagination,
  sieben Impfungen im CDA-Nachimport verifiziert. Patient-ID und Impfanzahl
  bleiben sichtbar; keine automatische Zusammenfuehrung von Patienten.
- QR-Vorschau: `/echosos/preview` dekodiert ohne BridgeLink-/FHIR-Zugriff mit
  demselben Parser wie der Import. Alle erkannten Felder und originalen
  Parameter sichtbar, auch Medikamente und Freitext. Diese beiden Inhalte
  werden noch nicht als eigenstaendige FHIR-Ressourcen gespeichert.
- Stand deployt und auf `main` gepusht; letzter Funktionscommit `1ba65d4`.
  41 gezielte Python-Tests erfolgreich; Browserpruefungen fuer vollstaendige
  Vorschau und Kamera-/Dateiablauf mit simuliertem Import erfolgreich.
- Offen: Live-Keycloak-Redirect-Konfiguration weiter nicht unabhaengig
  verifiziert; frueherer `redirect_uri`-Fehler bleibt historischer Befund.
  Einen weiteren EchoSOS-Import gegen den korrigierten CDA-Patienten und
  Wiederholungsimport erst beim naechsten bewussten Benutzertest pruefen.
  Keine weiteren Patientenschreibzugriffe fuer den Tagesabschluss.

Details: [EchoSOS](echosos-fhir.md),
[BridgeLink/CDA](bridgelink-cda-usecases.md).

## Projektname

BridgeLink

## Vision

BridgeLink ist eine Healthcare-Integrationsplattform fuer die Transformation, Validierung, Orchestrierung und Speicherung klinischer Daten.

BridgeLink verbindet:

- KIS
- Praxissysteme
- Labor-Systeme
- FHIR-Plattformen

ueber standardisierte Schnittstellen.

---

## Zielarchitektur

Quellsystem
→ BridgeLink
→ Python Middleware
→ HAPI FHIR Lookup und Persistenz

---

## Komponenten

### BridgeLink

Verantwortlich fuer:

- Workflow-Orchestrierung
- Routing
- Monitoring
- Auftragssteuerung

### Python Middleware

Verantwortlich fuer:

- CDA-Parsing
- Domain-Transformation
- FHIR-Mapping
- FHIR-Bundle-Erzeugung
- HAPI-Lookup und Referenzaufloesung
- direkte Importvorbereitung fuer BridgeLink und HAPI FHIR
- Bundle-Dedupe

### HAPI FHIR

Verantwortlich fuer:

- FHIR-Repository
- Source of Truth
- Ressourcenverwaltung

---

## Aktuelle Technologie

### Backend

- Python 3.12
- FastAPI

### Infrastruktur

- Docker
- Docker Compose

### Standards

- FHIR

---

## Betriebsnotiz: Middleware, HAPI und PostgreSQL

Stand: 2026-09-24

### Datenfluss

```text
Python Middleware (001-l-hlt01 / 10.20.30.212)
  -> http://hapi-fhir:8080/fhir
HAPI FHIR (001-l-hlt01)
  -> PostgreSQL auf 001-l-dat01 / 10.20.30.213:5433
postgres-fhir
```

Middleware und HAPI teilen das externe Docker-Netzwerk `proxy`. Der PostgreSQL-Container laeuft jedoch auf einer anderen Docker-VM. Deshalb ist `postgres-fhir:5432` von HAPI aus nicht verwendbar.

### Relevante Ports

| Dienst | Host | Port |
|---|---|---|
| Middleware | 001-l-hlt01 | 8000, 8082 |
| HAPI FHIR | 001-l-hlt01 | 8090 -> 8080 |
| PostgreSQL | 001-l-dat01 | 5433 -> 5432 |
| BridgeLink | 001-l-hlt01 | siehe interne Portangaben in `docs/architecture.md` |

### Konfiguration

In `/opt/python-middleware/docker-compose.yml`:

```yaml
FHIR_BASE=${FHIR_BASE:-http://hapi-fhir:8080/fhir}
```

In `/opt/docker/hapi-fhir/application.yaml` muss die Datenbankverbindung auf die Datenbank-VM zeigen:

```yaml
spring:
  datasource:
    url: "jdbc:postgresql://10.20.30.213:5433/fhir"
```

Benutzername und Passwort muessen mit der PostgreSQL-Konfiguration uebereinstimmen. Die Datenbank muss `fhir` heissen und Verbindungen von `10.20.30.212` erlauben.

### Aktueller Betriebsstand

HAPI laeuft stabil auf `001-l-hlt01`; `http://127.0.0.1:8090/fhir/metadata`
liefert HTTP 200. Die Datenbank liegt weiterhin auf `001-l-dat01`.

Nach Neustarts pruefen:

```bash
docker restart hapi-fhir
docker logs -f hapi-fhir
curl http://127.0.0.1:8090/fhir/metadata
```

Die direkte Middleware-Domain `https://middleware.local.omnilink.ch` liefert
Dashboard, Testclients und Middleware-Endpunkte. Terminologie und der VACD-
Referenzserver liefern HTTP 200 über ihre jeweiligen `/metadata`-Pfade.

Seit 2026-10-30 sind Convert und Import extern getrennt: Der externe Aufruf
`https://api.omnilink.ch/v1/cda/convert` konvertiert nur noch und liefert das
Transaction-Bundle zurueck (kein HAPI-Write); `https://api.omnilink.ch/v1/cda/import`
konvertiert und schreibt via BridgeLink nach HAPI. Der interne `POST /cda/import`
an die Middleware ist ein Proxy auf die externe Import-Route; `POST /cda/convert`
arbeitet vollstaendig read-only gegenueber HAPI.

Optional kann spaeter ein interner DNS-A-Record gesetzt werden:

```text
postgres.int.omnilink.ch. A 10.20.30.213
```
- CH Core
- CDA

HL7v2-Strukturen sind im Repository angelegt, der aktive API-Pfad ist derzeit jedoch CDA-zentriert.

---

## Software-Architektur

Parser
→ Converter und Domain Layer
→ Mapper und Builder
→ FHIR Bundle und HAPI Integration

---

## Parser

### CDA

- Patient Parser
- Practitioner Parser
- Organization Parser
- Encounter Parser
- Section Parser

### HL7v2

- Verzeichnisstruktur vorhanden, aktuell nicht ueber die FastAPI-Endpunkte exponiert

---

## Domain Layer

Aktuelle Domaenenmodelle:

- Patient
- Practitioner
- Organization
- Encounter
- Clinical Note

---

## Builder

- CH Core Patient
- CH Core Practitioner
- CH Core PractitionerRole
- CH Core Organization
- CH Core Encounter
- DocumentReference
- Binary
- Observation

---

## Mapper

- Allergy
- CareTeam
- Condition
- Consent
- Goal
- Immunization
- Laboratory
- Medication
- Organization
- Procedure
- Vital Signs

Clinical Notes werden nicht ueber einen klassischen Mapper, sondern ueber die Clinical-Note-Extraktion und DocumentReference/Binary-Builder umgesetzt.

---

## Services

- CDA Bundle Service
- Patient Service
- Practitioner Service
- Organization Service
- UMZH Convert Service
- UMZH Send Service

## Middleware-Implementierung

- Python-FastAPI-Anwendung aus `app/main.py`
- CDA-Parsing ueber `app/parser/cda/*.py`
- Clinical-Note-Extraktion ueber `app/converter/clinical_note_extractor.py`
- CH-Core- und DocumentReference-Builder in `app/builders/*.py`
- FHIR-Bundle-Assembly mit `build_bundle_entry()` und `cda_to_fhir_bundle()`
- HAPI-FHIR-Integration ueber HTTP-Requests zum FHIR-Server
- Bundle-Dedupe fuer `POST` anhand Identifiern oder Payload-Hash
- Import-Stabilisierung fuer Einzelressourcen und Dokumentbundles

## Deployment und Infrastruktur

- Docker-Compose-Service `middleware` in `docker-compose.yml`
- verwendet das externe Netzwerk `proxy`
- bindet an internen Port `8000`
- Containername: `python-middleware`
- Lokaler HTML-Testserver: `http://localhost:8082`
- HTML-Login: Keycloak Realm `omnilink`, Authorization Code + PKCE `S256`, ohne Client Secret
- FHIR-Backend: `http://hapi-fhir:8080/fhir`
- Standard-Importpfade liefern Transaction-Bundles an BridgeLink zur Weiterleitung an HAPI FHIR
- Anforderungen in `requirements.txt`:
  - fastapi
  - uvicorn
  - requests
  - python-multipart

---

## Duplicate-Check-Strategie

Vor Import nach HAPI FHIR:

- Patient-Matching anhand Identifier
- Practitioner-Matching anhand Identifier
- Organization-Matching anhand Identifier
- fuer Practitioner und Organization erfolgt Create inzwischen deterministisch per stabilem `PUT ResourceType/{uuid5}` statt per offenem `POST`
- bei Mehrfachtreffern auf bestehende Practitioner oder Organizations wird ein kanonischer Datensatz deterministisch bevorzugt
- Observation- und Procedure-Dedupe auf Bundle- oder Mapper-Ebene
- fuer `POST` wird nicht mehr nur nach `(method, url)` dedupliziert, sondern nach fachlicher Identitaet oder Payload-Hash
- einzelne FHIR-Ressourcen werden vor dem Import automatisch als Transaction-Bundle verpackt
- Dokumentbundles (`Bundle.type=document`) werden vor dem Import als Transaction-Bundle vorbereitet
- fehlende `entry.request`-Angaben werden aus Ressourcentyp und ID als `PUT` oder `POST` abgeleitet
- fuer `PUT` bleibt Dedupe anhand `(method, url)` aktiv
- bei vorhandenem Identifier erfolgt Aktualisierung per `PUT ResourceType/{id}` nach Server-Lookup statt Query-Conditional-URL
- Procedure-Mapping nutzt gemeinsamen Kontext pro Importlauf, um echte In-Run-Doppler frueh zu verwerfen

Ziel:

Vermeidung doppelter Ressourcen und idempotente FHIR-Imports.

---

## API-Endpunkte

### CDA

- `POST /cda/debug` — detaillierte CDA-Analyse im Debug-Modus
- Intern: `POST /cda/convert` — konvertiert CDA zu einem FHIR-Transaction-Bundle (read-only, kein HAPI-Write)
- Intern: `POST /cda/import` — Proxy auf BridgeLink; BridgeLink schreibt nach HAPI
- Extern ueber BridgeLink: `POST https://api.omnilink.ch/v1/cda/convert` (nur Konvertierung, seit 2026-10-30)
- Extern ueber BridgeLink: `POST https://api.omnilink.ch/v1/cda/import` (CDA-Import nach HAPI, seit 2026-10-30)
- `POST /emediplan/import-bundle` — stabilisiert und validiert ein FHIR-Resource-Objekt oder Bundle fuer BridgeLink
- `POST /cda/umzh/convert` — konvertiert CDA in UMZH-Workflow-Bundle mit Stages `initial|updated|completed`
- `POST /cda/umzh/send` — kombiniert UMZH-Convert mit Versand an ein Ziel-FHIR-System und liefert einen Versandreport
- `POST /cda/etoc/convert` — erzeugt einen CH-eTOC-orientierten `Bundle.type=document`-Pfad (Composition zuerst, inkl. Order-Referral/Purpose-Sections)
- `POST /cda/vacd/convert` — erzeugt ein CH-VACD Immunization Administration Document (`Bundle.type=document`, Composition zuerst)

### eMediplan

- `POST /emediplan/convert` und `POST /emediplan/import` akzeptieren CHMED16A-Text sowie PDF/Bild mit QR-Code.
- `POST /emediplan/qr/convert` und `POST /emediplan/qr/import` sind die expliziten QR-Dateipfade.
- `Medicaments[].PrscbBy` enthaelt laut CHMED16A entweder GLN oder Bezeichnung des Verordners.
- Gueltige GLNs werden per GS1 Modulo 10 geprueft und als CH-Core-Practitioner mit `identifier.system=urn:oid:2.51.1.3` erzeugt.
- `app/services/refdata_service.py` fragt die refdata.ch Partner SOAP API best-effort ab und ergaenzt Name und Adresse; fehlende Konfiguration, Fehler oder nicht gefundene GLNs blockieren den Import nicht.
- Nicht als GLN erkennbare `PrscbBy`-Werte bleiben als `MedicationStatement.informationSource.display` erhalten.
- Das separate Top-Level-Feld `Auth` ist der Dokumentautor und wird nicht als Verordner-GLN interpretiert.

### Metadata

- `GET /metadata` — nur im Debug-Modus verfuegbar

### CH VACD Convert

Der CH-VACD-Pfad erzeugt ein Dokument nach CH VACD 1.0.0. Für den openEHR-basierten Versand wird die offizielle Definition https://fhir.ch/ig/ch-vacd/1.0.0/immunization-administration-document.html verwendet. Das Bundle trägt das offizielle CH-VACD-Dokumentprofil; die erste Ressource ist eine Composition mit dem CH-VACD-Composition-Profil. Immunizations tragen das CH-VACD-Immunization-Profil.

Der Pfad bereinigt generische CDA-Inhalte und behält nur Ressourcen, die für das Immunization-Administration-Dokument benötigt werden. Die Patient- und Impfungsreferenzen werden auf die jeweiligen Bundle-`fullUrl`s aufgelöst. Bekannte Impfprodukte werden in `vaccineCode.coding` mit CVX, SNOMED CT und Swissmedic abgebildet.

### Test-Endpunkte

- `GET /test/patient` — testet Patient-Import und Lookup
- `GET /test/organization` — testet Organization-Import und Lookup

---

## Aktueller Ausbaustand

Vorhanden:

- CDA-Parsing
- HL7v2-Grundstruktur im Repository
- CH-Core-Builder
- Clinical-Note-Extraktion
- DocumentReference- und Binary-Erzeugung
- FHIR-Bundle-Erstellung
- HAPI-Lookup sowie Create- und Update-Integration fuer Referenzressourcen
- Patient-, Practitioner- und Organization-Service-Implementierung
- Fehlerbehandlung bei XML-Parsing und FHIR-Server-Antworten

---

## Aktuelle Roadmap

### Phase 1

- CDA → FHIR
- Referenzressourcen-Lookup und idempotenter Import

### Phase 2

- Clinical Notes
- DocumentReference
- Binary
- DiagnosticReport

Clinical Notes, DocumentReference, Binary und ein erstes UMZH-orientiertes DiagnosticReport-Mapping sind umgesetzt.

## Letzte Arbeiten

- UMZH-Workflow erweitert: `workflow_stage=initial|updated|completed` (inkl. Questionnaire und QuestionnaireResponse in spaeteren Stages)
- UMZH-Targeting erweitert: `target=sandbox-placer` erzeugt sandbox-kompatible absolute Referenzen
- Neuer Endpoint `POST /cda/umzh/send` implementiert (Convert + Versand per `PUT ResourceType/{id}` mit Ergebnis je Ressource)
- Tests erweitert: Convert-Stages, Sandbox-Target und Send-Service sind automatisiert abgesichert
- UMZH-Workflow erweitert: DiagnosticReport wird jetzt als Teil des Referral-Bundles erzeugt (`basedOn` -> ServiceRequest, `result` -> Observation, optional `presentedForm` aus DocumentReference)
- Domain/Builder-Layer erweitert: `ServiceRequest`, `Task` und `DiagnosticReport` sind als dedizierte Domain- und Builder-Bausteine implementiert und im UMZH-Convert-Service verdrahtet
- CH eTOC v3.0.1 im Blick: ServiceRequest wird mit zusaetzlichem CH-eTOC-Profil (`http://fhir.ch/ig/ch-etoc/StructureDefinition/ch-etoc-servicerequest`) markiert
- Zweiter Konvertierungspfad umgesetzt: `cda_to_etoc_document_bundle()` plus Endpoint `POST /cda/etoc/convert` fuer CH-eTOC-Dokument-Bundles (`type=document`, Composition-first, CH-eTOC-Profile auf Bundle/Composition)
- CH-eTOC Observation-Profilierung im Dokumentpfad umgesetzt: vorhandene diagnostische Observations werden heuristisch auf CH-eTOC-Profile gemappt (Lab/Pathology/Radiology/Cardiology), initial abgesichert fuer Lab-Observation
- Server-basierter Abnahme-Check ergaenzt: `app/scripts/etoc_acceptance_check.py` prueft CapabilityStatement, `/cda/etoc/convert`, Bundle-Shape, `$validate` und optional Persistenz gegen den Ziel-FHIR-Server
- CI erweitert (Mono-Repo): separater Workflow fuer `fhir-middleware` (Python-Tests) und separater Workflow fuer `fhir-server` (docker-compose + Nginx-Konfigurationschecks + Pflicht-IG-Keys)
- Isolierter Matrix-Stack im Repo angelegt: `fhir-server/matrix` mit eigenem Compose, `.env.example`, Nginx-vHost-Beispiel und Betriebs-README (keine Kollision mit FHIR-Ports)
- Produktives Edge-Routing: Matrix-Endpunkte (`/_matrix`, `/_synapse/client`, `/.well-known/matrix/*`) bleiben ein separater Pfad und werden nicht ueber die FHIR-Middleware geroutet
- Stabilisierung: Matrix-Proxy in Nginx auf `127.0.0.1:8008` umgestellt, damit Nginx auch dann startet, wenn `matrix-synapse` (Docker-DNS) noch nicht verfuegbar ist
- Matrix-Inbetriebnahme bleibt vom FHIR- und HTML-Lab getrennt; Matrix ist kein Middleware-Use-Case
- Nginx-Matrix-Upstream gehaertet: Docker-DNS mit `resolver 127.0.0.11` und variablem Upstream `matrix-synapse:8008` zur Laufzeitaufloesung
- TLS fuer Matrix aktiviert: Let's-Encrypt-Zertifikat fuer `matrix.woess.ch` via HTTP-01 Webroot ausgestellt; dedizierter Nginx-vHost (`matrix.woess.ch` auf 80/443) live aktiviert und erfolgreich validiert
- Matrix-Testseite bereitgestellt: statische HTML-Smoketest-Seite unter `/matrix-test/` mit Browser-Checks fuer `/_matrix/client/versions`, `/.well-known/matrix/*` und Federation-Key-Endpunkt
- Matrix-Testseite erweitert: Login-Testformular fuer `m.login.password` auf `/_matrix/client/v3/login` inkl. HTTP-Status und JSON-Response-Anzeige
- Matrix Import Bot umgesetzt: verarbeitet eMediplan-PDF/Bild und CDA-XML und antwortet im Raum mit Importstatus.
- Bot-Identitaetsgate gehaertet: unbekannte Absender und Abweichungen bei Patientenname oder Geburtsdatum werden vor dem Import blockiert.
- Bot-Testoberflaeche auf private Zwei-Personen-Raeume begrenzt; bestehende Raeume mit weiteren Mitgliedern werden nicht angeboten.
- Self-Service-Identitaetsverwaltung umgesetzt: authentifizierte `GET/PUT /matrix-bot-api/identity`-Aufrufe duerfen nur das Profil des per Matrix-Token verifizierten Benutzers lesen oder schreiben.

- eMediplan-Import stabilisiert: interner MedicationReference-Rewrite auf `fullUrl` korrigiert, wenn Upsert-Lookups Resource-IDs aendern
- eMediplan-QR/PDF-Import umgesetzt: PDF-Seiten werden gerendert, QR-Codes aus PDF/PNG/JPEG gelesen und in CHMED16A-Payloads ueberfuehrt.
- eMediplan-`PrscbBy`-Mapping umgesetzt: gueltige GLN erzeugt deterministischen CH-Core-Practitioner mit OID-System `urn:oid:2.51.1.3`; Freitext bleibt als `informationSource.display` erhalten.
- refdata.ch Partner-API angebunden: SOAP-Operation `Download`, Authentifizierung per `subscription-key`, client-seitige GLN-Filterung fuer die Stage-Umgebung und fail-safe Name-/Adressanreicherung.
- FHIR Query Client erweitert: fachliche Medikationszusammenfassung und Detailansicht zeigen den Verordner mit GLN beziehungsweise `GLN: nicht vorhanden`.
- EPIC-CDA Patient-Export erweitert: `recordTarget/patientRole` mit Identifier, Adresse, Telecom sowie erweiterten demografischen Feldern aus FHIR Patient
- EPIC-Medikations-Export erweitert: `effectiveTime/low`, `doseQuantity` und klinische Kommentar-Notizen aus FHIR MedicationStatement
- CDA-Import fuer Medikation erweitert: `originalText` und `translation` aus CDA-Code werden erhalten und in FHIR `medicationCodeableConcept.coding` uebernommen
- End-to-End validiert: `CDA-EPIC.xml` kann reimportiert werden und liefert im Export wieder strukturiertes Medication-Coding
- EPIC-Medikationslayout finalisiert: Export wieder im CDA-EPIC-List-Stil (`title=EPIC Medication Export`, `section/title=Medications`, `moodCode=EVN`)
- CH-EMED-nahe Produktanreicherung in eMediplan-Flow aktiv: optionale `Medication.form`, `Medication.ingredient`, `Medication.strength` aus Mapping
- API-Check clarified: Produktanreicherung sichtbar ueber Medication-Include (`_include=MedicationStatement:medication`), nicht direkt auf MedicationStatement

- Parser-Update fuer CDA-Immunization: Extraktion von `hl7:lotNumberText` und `manufacturerOrganization/hl7:name` aus `substanceAdministration`-Eintraegen
- CH-VACD-Dokumentpfad umgesetzt: `/cda/vacd/convert` erzeugt CH-VACD Immunization Administration Documents mit Bundle-/Composition-/Immunization-Profilen, UUID-Identifier, Composition-first und aufgelösten Referenzen
- CH-VACD-Filter umgesetzt: generische Abschnitte und unreferenzierte Ressourcen werden aus dem VACD-Dokument entfernt
- CH-VACD-Terminologie erweitert: bekannte Impfprodukte werden als CVX/SNOMED-CT/Swissmedic-Coding-Kette ausgegeben
- CH-VACD-Validierung abgesichert: vier fokussierte Regressionstests für Bundle-Struktur, Referenzen, Filterung und Metadaten
- Fehler behoben: `text_node` ist jetzt korrekt im Immunization-Parser definiert, sodass Dosage-Text und freier Text wieder zuverlaessig erfasst werden
- FHIR-Bundle-Import: bestehende Ressourcen werden nicht mehr nur mit `ifNoneExist` erstellt, sondern bei vorhandenem Identifier nach Lookup per `PUT ResourceType/{id}` aktualisiert
- Bundle-Dedupe korrigiert: mehrere gueltige `POST` auf denselben Ressourcentyp bleiben erhalten
- Procedure-Dedupe ergaenzt: Duplikate werden bereits im Mapper erkannt und nicht erst im finalen Bundle verworfen
- Encounter-Doppelpfad entfernt: Section-Code `46240-8` mappt nicht mehr auf den Encounter-Mapper
- Clinical Notes werden aus narrativen CDA-Sections extrahiert und als `DocumentReference` mit referenzierten `Binary`-Ressourcen in das Bundle aufgenommen
- Patient-Import erweitert: `maritalStatus`, `deceasedBoolean`, `communication`, `contact`, `patient-birthPlace`, `patient-religion` und Contact-Identifier aus CDA werden in CH-Core-Patient uebernommen
- `participant/associatedEntity` aus CDA-MWO wird als `Patient.contact` mit CH-Core-`contactData` plus fachlicher Beziehung (`SPS`) abgebildet
- EchoSOS-QR/PKPass-Import: Patientensuche nach Vorname, Nachname und Geburtsdatum; Middleware liefert ein Transaction-Bundle an BridgeLink, das den HAPI-Write ausführt; `$everything` erfolgt separat nach erfolgreichem Write
- EchoSOS-Kontaktmodell erweitert: `Patient.contact` und `RelatedPerson` werden gemeinsam angezeigt; `ECON` kennzeichnet Notfallkontakte, PCP wird ueber `CareTeam.participant` und `Practitioner` referenziert
- CareTeam-Reimport abgesichert: Vorhandene PCP-Teilnehmer bleiben bei CDA-Updates erhalten, wenn der neue CDA-Abschnitt keinen PCP liefert
- EchoSOS-Observations klassifiziert: Labor mit `laboratory`, Vitalzeichen mit `vital-signs`, Sozialanamnese mit `social-history`; unklassifizierte Observations und Encounter werden nur in der Notfallansicht ausgeblendet
- EchoSOS-Blutgruppe standardisiert: LOINC `882-1` fuer kombinierte ABO/Rh-Werte; ABO `883-9` und Rh `10331-7` werden in der Anzeige kombiniert
- EchoSOS-QR-Auswahlen dekodiert: Allergien mit positionsbezogenen Reaktionen, medizinische Vorgeschichte sowie bis zu drei Notfallkontakte werden aus dem kompakten QR gelesen
- EchoSOS-FHIR-Persistenz erweitert: SNOMED-`AllergyIntolerance` und SNOMED-`Condition`; Patient als Recorder/Asserter und als Performer der Blutgruppen-Observation
- Explizite EchoSOS-Organspende-Angabe als `Consent` mit Scope `adr` und LOINC `42348-3`; nur Zustimmung/Ablehnung erzeugen Consent, Schweizer „kein Registereintrag“ und „keine Angabe“ nicht
- EchoSOS-Medikamentenauswahlen und Freitext werden dekodiert, sind aber noch nicht als eigene FHIR-Ressourcen persistiert; explizite Organspendeangaben erzeugen Consent wie oben beschrieben
- EchoSOS-Namensräume auf `https://fhir.omnilink.ch/fhir/NamingSystem/...` migriert; identifier-basierte Reimports bleiben beim Systemwechsel idempotent
- Stand 2026-10-21: EchoSOS-HTML nutzt den Same-Origin-Proxy `/echosos/import` zum in Bruno bestaetigten `POST https://api.omnilink.ch/v1/echosos/resolve` ohne zusaetzlichen FHIR-POST; Patient-ID aus `transaction-response`, danach lesender `$everything`-Aufruf ueber `/echosos/fhir/Patient/{id}/$everything`.
- EchoSOS-HTML: kompakter Bereich „Input auswählen“, Keycloak-Anmeldung mit verborgen vorbelegter Client-ID `app-omnilink-cardtest`; Basic Auth und lokale Passwortspeicherung entfernt
- Offen: Live-EchoSOS-Login meldet `Invalid parameter: redirect_uri`; gespeicherte Keycloak-Freigabe fuer `https://middleware.local.omnilink.ch/echosos-fhir-test.html` noch nicht verifiziert. Browserablauf nur mit synthetischem Token und simulierten Antworten getestet; Details in [TEST-CLIENT.md](../TEST-CLIENT.md#offener-keycloak-login-stand-2026-10-21)
- Schwangerschaftsstatus als Observation mit LOINC `82810-3` und SNOMED CT `77386006` abgebildet
- CDA-Autoren dokumentbezogen aufgeloest: ID-only-Authoren werden, wenn im selben CDA benannt, auf den vorhandenen Namen zurueckgefuehrt
- HAPI-Testbestand gezielt bereinigt: doppelte Patient-, Practitioner-, PractitionerRole-, Organization-, Observation- und CareTeam-Datensaetze entfernt
- Builder-Dedupe erweitert: redundante `name`, `telecom` und `address` werden fuer Patient und Practitioner vor dem Persistieren reduziert
- Infrastruktur stabilisiert: `hapi-fhir`, `bridgelink` und `fhir-middleware` verwenden das gemeinsame Docker-Netzwerk `proxy`
- verifiziert: Re-Imports bleiben fuer Referenzressourcen und deduplizierte Bundle-Eintraege idempotent

### Phase 3

- US Core Unterstützung

### Phase 4

- FHIR → CDA
- FHIR → HL7v2

### Phase 5

- Kafka Integration
- RabbitMQ Integration
- Microservice Aufteilung

---

## Entscheidungen

### ADR-001

BridgeLink orchestriert.
Middleware transformiert.

Status: Accepted

### ADR-002

HAPI FHIR ist Source of Truth.

Status: Accepted

### ADR-003

Parser, Domain, Mapper und Builder bleiben getrennte Schichten.

Status: Accepted

### ADR-004

FHIR Bundles werden an BridgeLink zurückgegeben.

Status: Accepted

### ADR-005

Clinical Notes werden über DocumentReference und DiagnosticReport umgesetzt.

Status: Proposed

---

## Aktueller Fokus

Status: Active Development

Aktuelles Epic:
US Core Clinical Notes

Aktuelle Aufgabe:
Analyse und Implementierung von:

- DocumentReference
- Binary
- DiagnosticReport

Nächstes Ziel:
Clinical Notes aus CDA Sections extrahieren und als FHIR-Ressourcen bereitstellen.

---

## Technical Debt

### Offen

- HL7v2 Parsing bisher nur Patient
- Keine Kafka Integration
- Keine RabbitMQ Integration
- Keine Provenance Ressourcen
- Keine Composition Ressourcen
- Keine Subscription Unterstützung

### Zu prüfen

- Vollständige US Core Kompatibilität
- Bulk Import Strategie
- Performance bei großen CDA Dokumenten
- CH eTOC Document-Konformitaet: fuer ein echtes CH-eTOC-Dokument ist ein `Bundle.type=document` mit `Composition` als erstem Entry erforderlich; aktueller UMZH-Pfad liefert bewusst ein Workflow-`Bundle.type=collection`
- CH eTOC Observation-Profile fuer diagnostische Ergebnisse (Lab/Pathology/Radiology/Cardiology) gezielt auf bestehende Observation-Mappings abbilden
- CH eTOC Observation-Profile fuer diagnostische Ergebnisse (Lab/Pathology/Radiology/Cardiology): initiale Heuristik aktiv; Feintuning gegen reale CDA-Stichproben und IG-Beispiele offen

---

## Letzte Session

Datum: 2026-07-23

Erarbeitet:

- Projekt-Memory erstellt
- Zielarchitektur dokumentiert
- HAPI PostgreSQL geprüft
- hfj_resource Tabelle festgestellt: 0 Ressourcen
- Vorbereitung US Core Clinical Notes

Nächster Schritt:

- Analyse bestehender CDA Sections
- Implementiertes Clinical Note Domain Model
- Implementierung DocumentReference Builder

---

## Dokument

Version: 1.1
Letzte Aktualisierung: 2026-07-28
Verantwortlich: Markus Wöss

## Laufzeitumgebung

### Docker Container

- fhir-middleware
- fhir-server (HAPI FHIR)
- fhir-postgres (PostgreSQL 16)
- fhir-adminer
- fhir-nginx

### Aktuelle Erkenntnisse

- HAPI FHIR nutzt PostgreSQL
- Tabelle hfj_resource wurde geprüft
- Aktueller Bestand: 0 Ressourcen

## Backlog - Nächste Schritte

### Clinical Notes

Status: In Planung

Tasks:

- [x] Clinical Note Domain Model erstellen
- [x] DocumentReference Builder erstellen
- [x] Binary Strategie definieren
- [x] CDA Narrative Mapping definieren
- [x] DiagnosticReport Mapping definieren (UMZH Referral Bundle, initiale Version)
- [ ] US Core Clinical Notes Tests erstellen

---

## BridgeLink - Analyse CH UMZH Connect IG

Stand: 2026-07-28

### Ziel

Bewertung der bestehenden BridgeLink-Architektur gegenueber dem HL7 Switzerland Implementation Guide CH UMZH Connect (R4) und Identifikation der notwendigen Erweiterungen fuer die Unterstuetzung von Referral- und Clinical-Order-Workflows.

### Ueberblick CH UMZH Connect

Das CH UMZH Connect IG definiert einen standardisierten FHIR-basierten Austauschprozess fuer:

- Ueberweisungen (Referrals)
- Externe Leistungsauftraege
- Verlegungen
- Interinstitutionelle klinische Kommunikation

Der Schwerpunkt liegt auf einem API-basierten Clinical-Order-Workflow zwischen einem Auftraggeber (Placer) und einem Auftragsempfaenger (Fulfiller).

### Zentrales Workflow-Modell

Das IG basiert auf dem HL7 Clinical Order Workflow (COW).

Grundprinzip:

```text
Placer
  |
  | erstellt ServiceRequest
  | erstellt Task
  v
Fulfiller

Task.basedOn -> ServiceRequest
```

Der Fulfiller uebernimmt die Verwaltung des Task-Lifecycles und informiert den Placer ueber Statusaenderungen und Ergebnisse.

Typische Task-Status:

```text
requested
accepted
in-progress
completed
cancelled
```

### Erwartete FHIR-Ressourcen

Workflow:

- ServiceRequest
- Task

Administrative Daten:

- Patient
- Practitioner
- PractitionerRole
- Organization
- Coverage

Klinische Daten:

- Condition
- MedicationStatement
- AllergyIntolerance
- Observation
- Procedure

Dokumente:

- DocumentReference
- Binary

Weitere Ressourcen:

- ImagingStudy
- Appointment
- DiagnosticReport

### BridgeLink Ist-Zustand

Bereits vorhanden

Administrative Ressourcen:

- Patient
- Practitioner
- PractitionerRole
- Organization
- Encounter

Klinische Ressourcen:

- Condition
- Observation
- Medication
- Allergy
- Procedure
- CareTeam
- Goal
- Immunization
- Consent

Dokumentenmodell:

- Clinical Note Domain Model
- DocumentReference Builder
- Binary Builder

Infrastruktur:

- CDA Parsing
- FHIR Bundle Builder
- HAPI FHIR Integration
- Idempotenter Import
- Referenzaufloesung

### Mapping BridgeLink -> UMZH Connect

Vollstaendig oder weitgehend abgedeckt

Patient

BridgeLink:

```text
Patient Domain
CH Core Patient Builder
```

Status: Vorhanden

Practitioner

BridgeLink:

```text
Practitioner Domain
CH Core Practitioner Builder
PractitionerRole Builder
```

Status: Vorhanden

Organization

BridgeLink:

```text
Organization Domain
CH Core Organization Builder
```

Status: Vorhanden

Condition

BridgeLink:

```text
Condition Mapper
```

Status: Vorhanden

Medication

BridgeLink:

```text
Medication Mapper
```

Status: Vorhanden

AllergyIntolerance

BridgeLink:

```text
Allergy Mapper
```

Status: Vorhanden

Observation

BridgeLink:

```text
Observation Builder
```

Status: Vorhanden

DocumentReference

BridgeLink:

```text
Clinical Note Extraction
DocumentReference Builder
```

Status: Vorhanden

Binary

BridgeLink:

```text
Binary Builder
```

Status: Vorhanden

### Identifizierte Luecken

1. ServiceRequest

Groesste fachliche Luecke.

Im UMZH-Modell repraesentiert der ServiceRequest:

- Ueberweisung
- Auftrag
- Klinische Fragestellung
- Gewuenschte Leistung

BridgeLink besitzt derzeit kein eigenes ServiceRequest-Domainmodell.

Empfehlung: Neues Domain Model

```python
class ServiceRequestDomain:
  identifier: str
  status: str
  intent: str

  patient_id: str

  requester: str
  recipient: str

  category: list[str]

  code: str

  reason_codes: list[str]
  supporting_info: list[str]
```

Status: Fehlt

2. Task

Im UMZH-Workflow steuert der Task den gesamten Prozess.

Aufbau:

```text
Task
 └── basedOn -> ServiceRequest
```

BridgeLink besitzt bereits Workflow-Stages:

```text
initial
updated
completed
```

Diese lassen sich direkt auf Task-Status abbilden.

Mapping-Vorschlag:

```text
initial
  -> requested

updated
  -> in-progress

completed
  -> completed
```

Status: Fehlt

3. DiagnosticReport

DiagnosticReport befindet sich bereits auf der Project Roadmap.

Besonders relevant fuer:

- Laborberichte
- Radiologie
- Tumorboard
- Pathologie

Empfohlene Struktur:

```text
DiagnosticReport
 ├─ code
 ├─ conclusion
 ├─ result
 └─ presentedForm
```

Status: Offen

### Empfohlene Erweiterung der Domain-Architektur

Aktuell:

```text
Patient
Practitioner
Organization
Encounter
ClinicalNote
```

Ziel:

```text
Patient
Practitioner
Organization
Encounter
ClinicalNote

ServiceRequest
Task
```

### Empfohlene neue Builder

ServiceRequest Builder

Datei:

```text
app/builders/servicerequest_builder.py
```

Verantwortlich fuer:

- Referral-Auftraege
- Clinical Questions
- Service Orders

Task Builder

Datei:

```text
app/builders/task_builder.py
```

Verantwortlich fuer:

- Workflow-Lifecycle
- Statusverwaltung
- Referenzierung des ServiceRequest

### Zielbild UMZH Referral Bundle

Heute:

```text
Patient
Practitioner
Organization

Condition
Observation

DocumentReference
Binary
```

Ziel:

```text
Patient
Practitioner
Organization

ServiceRequest
Task

Condition
MedicationStatement
AllergyIntolerance

Observation
Procedure

DocumentReference
Binary

DiagnosticReport
```

Dieses Bundle entspricht weitgehend dem fachlichen Kernmodell des CH UMZH Connect IG.

### Empfohlene Roadmap-Erweiterung

Clinical Notes Epic abschliessen

Offene Arbeit:

```text
DiagnosticReport Mapping
```

Neues Epic: UMZH Referral Workflow

Umfang:

- ServiceRequest Domain Model
- ServiceRequest Builder
- Task Builder
- Referral Bundle Assembler
- CH UMZH Connect Profilunterstuetzung
- Fulfiller/Placer Workflow-Unterstuetzung
- End-to-End Tests

### Strategische Bewertung

BridgeLink ist bereits deutlich mehr als ein einfacher CDA-Konverter.

Der aktuelle Funktionsumfang deckt bereits den groessten Teil der klinischen Inhalte des CH UMZH Connect IG ab.

Die wesentlichen fehlenden Bausteine sind:

1. ServiceRequest
2. Task
3. DiagnosticReport

Nach Umsetzung dieser Komponenten kann BridgeLink als vollstaendige Referral- und Clinical-Order-Workflow-Plattform auf Basis des CH UMZH Connect Standards positioniert werden.

Dadurch entwickelt sich BridgeLink von:

```text
CDA -> FHIR Converter
```

zu:

```text
FHIR Clinical Order and Referral Integration Platform
```

fuer Placer- und Fulfiller-Szenarien innerhalb des UMZH-Connect-Oekosystems.

## Epic FHIR Sandbox: Backend-OAuth mit Bruno (Stand 2026-10-28)

- Token-Endpunkt: `POST https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token` mit `grant_type=client_credentials` und `client_assertion` (RS256-JWT, `kid=epic-key-1`).
- Client-Assertion: Pre-Request-Script erzeugt sie pro Request neu (`jti` = neue UUID, `exp` = jetzt + 300 s). Der Private Key liegt nur als Secret `PEM` im Bruno-Environment `omnilink`, nie im Repo. Auf dem Server liegt nur der Public Key fuer das JWKS (`/.well-known/jwks.json`).
- Post-Response-Script speichert `accessToken` und `tokenExpiresAt` (ISO, UTC, 60 s Puffer) als Runtime-Variablen und loggt Scopes sowie Erneuerungszeit.
- FHIR-Requests: Auth-Typ Bearer Token mit `{{accessToken}}` (Inherit vom Ordner). Der Token-Request selbst steht auf No Auth.
- Scopes bestimmt Epic ueber die App-Registrierung auf fhir.epic.com, der `scope`-Parameter im Request wird ignoriert (Trenner waere ohnehin Leerzeichen).
- Ergebnis: `GET Patient/{id}` liefert 200 nach Freigabe von Patient.Read. `Immunization?patient=` und `Observation?patient=&category=vital-signs` liefern 403 `insufficient_scope`; vermutet wird, dass die Search-APIs an der App fehlen (nicht verifiziert).
- Offen: Search-APIs (Immunization, Observation, Patient, List) in der Epic-App ergaenzen, neuen Token holen, erneut testen. `Patient?identifier=FHIR|<id>` lieferte 404 (Code 59008, ungueltige FHIR-ID); Request-Pfad noch zu pruefen.
