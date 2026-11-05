# FHIR Middleware Test Client

`test-client.html` ist die BridgeLink API Werkbank. Freigeschaltet sind:

| Use Case | Request-Ziel | HAPI-Write |
|---|---|---|
| CDA Convert | BridgeLink `/v1/cda/convert` | Nein |
| CDA XML pruefen (Husky) | Same-Origin `/cda/source/validate?level=full|xsd` | Nein |
| CDA Validate (Transaction/Document) | Same-Origin `/cda/validate` | Nein |
| CDA FHIR-Bundle separat validieren | Same-Origin `/fhir/validate` | Nein |
| CH-EMED-EPR Medikationsliste: FHIR-Vorschau | Same-Origin `/fhir/medications/pmlc/from-server` | Nein |
| CDA Import | Same-Origin `/cda/import` -> BridgeLink | Ja |
| eMediplan JSON / CHMED16A Convert | BridgeLink `/v1/emediplan/convert` | Nein |
| eMediplan JSON / CHMED16A Import | BridgeLink `/v1/emediplan/import` | Ja |
| eMediplan FHIR-JSON Import | BridgeLink `/v1/emediplan/import` | Ja |
| eMediplan PDF/QR Convert | Same-Origin `/emediplan/qr/convert` | Nein |
| eMediplan PDF/QR Import | Same-Origin `/emediplan/qr/import` -> BridgeLink | Ja |
| EchoSOS-URL Import | BridgeLink `/v1/echosos/resolve` | Ja |
| Patient `$everything` | FHIR `Patient/{id}/$everything` | Nein |
| VACD Convert | BridgeLink `/v1/cda/vacd/convert` (Routing eingerichtet, Live-Abnahme offen) | Nein |
| VACD Validate | Same-Origin `/cda/vacd/validate` | Nein |
| CDA -> VACD zusaetzlich mit Husky pruefen | Same-Origin `/cda/vacd/husky/validate` | Nein |
| VACD FHIR-Bundle mit Husky pruefen | Same-Origin `/fhir/vacd/husky/validate` | Nein |
| VACD openEHR-Send | Same-Origin `/cda/vacd/send` | Externer Demo-FHIR-Server |

Der VACD-HAPI-Import ist aus der Werkbank entfernt und serverseitig
deaktiviert (HTTP 410 auch ueber die bisherige Importvorbereitung).
Der externe VACD-Sendeweg bleibt davon getrennt. Am 2026-11-05 wurde ein
erfolgreicher Testaufruf anhand der bereitgestellten Antwort belegt:
Patient neu angelegt, drei neue Impfungen, Dokumentantwort HTTP 201.
Das ist keine unabhaengige Lesepruefung oder vollstaendige fachliche Abnahme.
Er validiert jetzt verpflichtend intern vor dem ersten Zielkontakt und
erneut vor dem Dokumentversand. Fehler/fatal oder Validator-Ausfall
blockieren den naechsten Schritt. Warnungen bleiben im Sendebericht
unter `send.validation` sichtbar. Nach dem Patientenabgleich kann bei
einem Fehler der zweiten Pruefung bereits ein Zielpatient existieren.
Die Validierung liefert ein OperationOutcome mit allen Fehlern und Warnungen;
auch bei HTTP 200 wird `error`/`fatal` als Fehler angezeigt.
Husky-Befunde ohne explizite Einzelprofilangabe werden nun als
`Ressourcenprofil (Kontext)` anhand des betroffenen Bundle-Eintrags
gruppiert. Ohne eindeutige Ressourcenzuordnung wird das Dokumentprofil
als `Prueflauf (Einzelprofil nicht angegeben)` angezeigt. Das behauptet
keine kausale Zuordnung zum Ressourcenprofil und zaehlt keine Befunde doppelt.
Medikationsimporte aus eMediplan werden vor der BridgeLink-Freigabe
verpflichtend intern profilvalidiert (422 bei Fehlern, 502 bei Ausfall).
CDA-Importe benoetigen dafuer das neue Gateway-Ziel `/cda/prepare`;
OL_ROUTING und Channel-XML sind lokal aktualisiert, der Live-Channel muss
noch gespeichert und neu deployt werden. Der Convert-Usecase bleibt ohne
Importsperre. HAPI-Altdaten werden nicht automatisch korrigiert.
Fuer bereits konvertierte CDA-Bundles (einschliesslich eTOC/UMZH) steht die
separate JSON-Bundle-Validierung zur Verfuegung. Kein automatischer Import
nach einer erfolgreichen Validierung.
Routing und Grenzen:
[CH-VACD](docs/ch-vacd-immunization-administration.md).

Die beiden zusaetzlichen Husky-Aktionen pruefen gegen das stabile
CH-VACD-6.0.0-Immunization-Administration-Profil und deklarierte Profile,
vollstaendig intern mit lokalen Paketen. Fehler und Warnungen erscheinen
in der vorhandenen Profiluebersicht. Fuer das bestehende FHIR-Bundle die
JSON-Aktion verwenden: keine erneute Konvertierung oder Aenderung.
HTTP 422 bedeutet Profilfehler, 502 einen nicht abgeschlossenen Prueflauf.
HAPI-Pruefung und Versand werden dadurch weder ersetzt noch automatisch
ausgeloest; die neue Pruefung ist ein eigener, bewusst auszuwaehlender Lauf.
Keine klinische Impfempfehlung oder Speicherung. Die Husky-Pruefung bleibt
offline; die bestehende CDA-Konvertierung behaelt ihre Lese-/Abgleichschritte.

### CDA-XML-Eingangspruefung

Die neue Husky-Aktion prueft das Original-XML, nicht das FHIR-Bundle.
Die Auswahl `full` verlangt XSD und passende Profil-Schematrons;
fehlende Profilregeln erscheinen ausdruecklich als Fehler.
Aktuell ist die CDA-R2-XSD aktiv, passende offizielle EPIC-/AT-Schematrons
sind noch nicht installiert. `xsd` ist nur eine Strukturpruefung.
Keine Konvertierung, kein Import, kein externer klinischer Request.
[Abdeckung und Betrieb](husky-validator/README.md).

### CH-EMED-EPR-FHIR-Vorschau

Patient-ID explizit angeben. Es werden nur aktive MedicationStatements
aus dem internen HAPI verwendet, keine Rezepte. Sprache und
Vertraulichkeit sind waehlbar (Defaults de-CH/restricted).
Die Middleware prueft den Keycloak-Access-Token vor jedem Datenabruf.
Der vorhandene Werkbank-Token wird unveraendert mitgesendet.
Die Middleware erlaubt den signierten Client `azp=app-omnilink-cardtest`,
ohne zusaetzliche Realm-Rolle. Fremde Clients werden abgewiesen;
Signatur, Issuer und Ablauf werden weiterhin zwingend geprueft.
Das Ergebnis enthaelt Dokument und echten internen Pruefbericht.
Fehler im HTTP-422-Bericht bleiben nach Profil sichtbar.
Ein separater Button laedt nur das FHIR-Dokument als Vorschau herunter;
der normale Antwortdownload bleibt der unveraenderte Gesamtbericht.

Die vorgeschriebene PDF/A-Originaldarstellung fehlt bewusst bis zum
naechsten Ausbau. Daher ist dies **keine freigegebene, profilkonforme
Medikationskarte**. Keine Speicherung und kein automatischer Import.
[Details](docs/ch-emed-epr-pmlc.md).

### Profiluebersicht der Validierungsantwort (2026-11-05)

Die Werkbank zeigt ueber dem unveraenderten JSON eine Gesamtzahl der Fehler
(einschliesslich fatal), Warnungen und Informationen sowie eine Tabelle
der Fehler/Warnungen nach Profilangabe. Aufklappbare Zeilen enthalten
Diagnostik und betroffene Felder. Informationen werden nur in der Gesamtzahl
beruecksichtigt, nicht als Fehler einer nicht passenden Slice gezaehlt.

Die Profilzuordnung stammt aus StructureDefinition-URLs in `diagnostics`
oder `details.text` des OperationOutcome. Versionen bleiben erhalten.
Explizite CDA-Pruefgruppen des Husky-Dienstes werden aus der Extension
`urn:omnilink:validation:profile` uebernommen und haben Vorrang vor Textsuche.
Mehrere genannte Profile bilden eine gemeinsame Gruppe; eine Meldung wird
nicht mehrfach gezaehlt. Ohne Profilangabe steht die Meldung unter
„Profil nicht eindeutig angegeben“. Die Tabelle ist keine Liste aller
geprueften Profile und kein separater Konformitaetsnachweis pro Profil.

Beide VACD-Sendepruefungen werden separat angezeigt. Validator-/Importfehler
bleiben Fehler; Warnungen erhalten einen gelben Status statt einer rein
gruenen Erfolgsmeldung. JSON-Download und Antwortwiederverwendung enthalten
weiterhin den originalen Body. Neue Requests loeschen alte Zusammenfassungen
und Antwortmetadaten, damit Netzwerkfehler keinen alten HTTP-200-Stand zeigen.

### Externes VACD-Ergebnis

Vor den internen Validierungen steht **Externer FHIR-Server: Ergebnis**:
Patientenanlage oder Wiederverwendung, Zielpatient-ID, neue/ausgelassene
Impfungen, Dokument-HTTP-Status und Kennungen der Zielantwort.
Ressourcentyp-Zaehler beschreiben den Antwortinhalt, nicht einzeln
bestaetigte Neuanlagen. Die Originalantwort ist separat aufklappbar.
`sent` bedeutet erfolgreich gemeldeter Versand; `skipped` bedeutet
ausdruecklich kein neuer Dokumentversand. Es wird keine automatische
Lesepruefung oder direkte openEHR-Composition-Anlage behauptet.

Die Erweiterung ist auf dem Testsystem deployt. 46 VACD-Python- und
22 Werkbank-Node-Tests bestanden; die neue Ergebnisansicht wurde im Browser
mit synthetischer Antwort ohne externen Write geprueft.
Bruno-GETs fuer die unabhaengige Lesepruefung:
[VACD-Dokumentation](docs/ch-vacd-immunization-administration.md).

### Validierungsstichprobe vom 2026-11-04

Am deployten System mit der lokalen CDA-EPIC-Stichprobe geprueft:

| Validierung | Fehler | Warnungen |
|---|---|---|
| CDA Transaction | 0 | 186 |
| CDA Document | 0 | 84 |
| VACD Document | 0 | 27 |

Die Sperren `/cda/vacd/prepare` und `/cda/vacd/import` liefern HTTP 410.
Synthetische Negativtests bestaetigen die Weitergabe eines ungueltigen
FHIR-Enumerationswerts als HTTP 400 mit Originaldiagnostik sowie eines
unbekannten Profils als Fehler im HTTP-200-OperationOutcome.
93 Python- und 32 Node-Regressionstests bestanden. Die neue Auswahl,
der Verarbeitungsweg ohne Speicherung und die Entfernung des VACD-Imports
wurden im Browser auch bei 390 Pixeln Breite geprueft. Kein klinischer
Import und kein externer VACD-Versand wurden dabei ausgefuehrt.

Weitere im Quellcode enthaltene Use-Cases bleiben ausgeblendet, solange ihre
Gateway-Routen nicht freigegeben sind. eMediplan-JSON wird als
`application/json`, CHMED16A als `text/plain; charset=utf-8` und FHIR-JSON als
`application/fhir+json` gesendet. PDF-/QR-Dateien gehen als Multipart-Upload
an die Middleware, nicht direkt an den BridgeLink HTTP Listener.
Der freigegebene CDA-Import verwendet Keycloak Authorization Code mit PKCE
und leitet authentifizierte Requests ueber `POST /cda/import` an
`https://api.omnilink.ch/v1/cda/import` weiter. Die Client-ID
`app-omnilink-cardtest` ist wie beim EchoSOS-Client verborgen vorbelegt.
Ausgewaehlte UTF-8-XML-Dateien werden ohne Multipart-Huelle als Raw-Body
mit `Content-Type: application/xml; charset=UTF-8` gesendet. Fuer eingefuegten
XML-Text gilt derselbe Header. FHIR-`OperationOutcome`-Fehler und fehlgeschlagene
Bundle-Eintraege werden auch bei HTTP 200 als Fehler angezeigt.
Die Routenanzeige kennzeichnet Same-Origin-Aufrufe als Datei-Upload bzw.
Middleware-Aufruf, ohne interne Middleware-Pfade oder URLs anzuzeigen.
Das gilt auch fuer die Antwort-Metadaten. Browser-Netzwerkdetails enthalten
weiterhin die technisch erforderliche Request-URL; dies ist keine Zugriffssperre.
Das Routenfeld zeigt den konfigurierten Verarbeitungsweg in einer eigenen
Zeile, darunter bei direkten BridgeLink-/FHIR-Aufrufen den Request-Pfad.
Lange Angaben werden umgebrochen statt abgeschnitten. Auch die Antwort-Metadaten zeigen den
Verarbeitungsweg, z. B. `Middleware -> BridgeLink -> HAPI` beim PDF-/QR-Import.
Angezeigte externe Request-URLs entsprechen den vom Browser aufgerufenen Adressen;
der Verarbeitungsweg ist keine Laufzeit-Tracing-Bestaetigung aller Stationen.
Der originale FHIR-Antwortbody bleibt unveraendert, einschliesslich interner
Adressen unter `link.self`; diese werden bewusst nicht umgeschrieben.

## Aktueller Betriebsstand (2026-11-04)

- Tagesabschluss: Middleware mit separater Validierung und verpflichtender
  externer VACD-Sendepruefung deployt. VACD-HAPI-Import bleibt deaktiviert.
- Abschliessender Regressionstest vor Git-Sync: 99 Python- und 41 Node-Tests
  bestanden; beide Git-Remotes vor dem Commit ohne Divergenz.
- CORS im Channel korrigiert: nur Preflight fuer den exakten Werkbank-Origin
  darf ohne JWT passieren; echte Aufrufe bleiben JWT-geschuetzt.
  Live bestaetigt: OPTIONS 204 mit CORS-Headern und Browser-CDA-Convert
  200/transaction mit erfolgreicher JWT-Pruefung, ohne HAPI-Write.
  Bruno-Erfolg allein prueft keine Browser-CORS-Regeln.
- Frischer Channel-Export Revision 114 wurde gegen die versionierten
  Routing-/Transformerquellen und Listener-Einstellungen abgeglichen.
- Separate JSON-Bundle-Validierung lieferte auch ueber die oeffentliche
  Middleware-Adresse und im Browser ein OperationOutcome (HTTP 200).
  Dies ist kein Nachweis fuer die zusaetzlichen Gateway-Validierungsrouten.
- Generisches CDA liefert CH-Core-Compositions mit urspruenglichem
  CDA-Dokumenttyp, nicht mehr pauschal CH IPS. Interne HAPI-Pruefung der
  CDA-EPIC-Stichprobe: Transaction und Document jeweils 0 Fehler.
  186 bzw. 84 Warnungen bleiben; keine vollstaendige Terminologieabnahme.
  Details: [CDA-Korrekturen](docs/bridgelink-cda-usecases.md).
- Werkbank-Anpassungen sind gebaut und deployt. Die Routenanzeige wurde im
  Browser bei 1440, 808 und 390 Pixeln Breite ohne Abschneiden geprueft.
- Dispatcher-Revision 114 verwendet OL_CORE und OL_ROUTING; JWT-Validierung
  fuer echte Requests bleibt erhalten. Listener, Source-Transformer und
  Destination-99-Response-Transformer behandeln jetzt CORS-Preflights.
- Nach der Auslagerung: CDA Convert (200/transaction), eMediplan Convert
  (200/collection) und unbekannter Endpunkt (404/OperationOutcome) bestaetigt.
- PDF-/QR-Import liefert weiterhin 200/transaction-response; die gezeigte
  Observation blieb auf Version 1. Keine neue Vollpruefung aller Ressourcen.
- 41 Werkbank-/Core-/Routing-/CORS-Tests bestanden.
- VACD-Live-Abnahme, 400-/401- und Ausfalltests nach dem Refactoring sind offen.

Channel-Snapshot, Library-Importe, Rollback und Sync beider Git-Remotes:
[BridgeLink-Dokumentation](bridgelink/README.md).

### Offene Punkte fuer die Fortsetzung

- Warnungen aus den Profilpruefungen fachlich/terminologisch auswerten;
  fehlerfreie Stichproben sind keine pauschale IG-Abnahme.
- Vollstaendiger CH-EMED-Dokumentworkflow und spaetere IPS-Erzeugung
  aus HAPI bleiben separate Vorhaben.
- Kein echter externer VACD-Live-Versand: beide HAPI-Pruefungen mit lokaler
  CDA-Datei bestanden, externe Patienten-/Bundle-Schritte nur simuliert.
- Alle Gateway-Routen nach CORS-Aenderung authentifiziert nachtesten,
  insbesondere Fehlerantworten/Tokenablauf, ohne unbeabsichtigte Writes.
- Eine verpflichtende FHIR-IG-Validierung vor saemtlichen bestehenden
  Importwegen ist noch nicht implementiert.

## eMediplan-Abnahme (2026-11-04)

- FHIR-R4-Strukturkorrektur: Collection-Eintraege erhalten stabile UUID-fullUrls;
  lokale Referenzen verwenden diese URLs. Ressourcen-IDs und fachliche
  Identifier bleiben unveraendert. Die Transaction-Aufbereitung beruecksichtigt
  die bisherigen fullUrls beim Umschreiben der Referenzen.
- Ein synthetisches Konverter-Bundle wurde intern mit HAPI `Bundle/$validate`
  erneut geprueft: 0 Fehler, 4 Warnungen, 2 Hinweise (vorher 6 Fehler).
  Narrative-/GTIN-Hinweise und CH-EMED-MedicationStatement-Abweichungen bleiben
  offen; dies ist keine vollstaendige CH-EMED-Dokumentabnahme.
- VACD besitzt bereits UUID-fullUrls und Referenzumschreibung. Die
  Dokumentaufbereitung entfernt jetzt zusaetzlich Transaction-Felder
  `entry.request` und `entry.response`. Struktur-/Importregressionen:
  insgesamt 51 Python-Tests bestanden. Vollstaendige VACD-Profilabnahme offen.

- JSON-/CHMED16A-Konvertierung und PDF-/QR-Konvertierung liefern ein
  FHIR-`collection`-Bundle ohne HAPI-Write.
- JSON- und PDF-/QR-Import wurden bis HAPI getestet; die Antwort ist ein
  `transaction-response`-Bundle.
- Wiederimporte der beiden Testplaene verwenden die bestehenden Patienten
  und Ressourcen wieder. Die anschliessenden `$everything`-Abfragen zeigten
  weiterhin Version 1 fuer alle zurueckgegebenen Ressourcen.
- Pharmacode-/GTIN-Anreicherung wurde anhand gespeicherter Medications
  bestaetigt. Nicht aufgeloeste Codes bleiben als Quellcode erhalten;
  Freitextmedikamente koennen ohne strukturierte Codings vorliegen.
- Name und Adresse eines gespeicherten Practitioners wurden mit dem lokalen
  Refdata-NAT-Datensatz verglichen und stimmten ueberein. Das bestaetigt
  die Anreicherung, nicht die Aktualitaet des Live-Registers oder eine
  Verordnungsberechtigung.

Zur eigenen Pruefung erst importieren, dann dieselbe Eingabe erneut senden
und `entry[].response.status` sowie IDs/Versionen per `$everything` vergleichen.
Ein vorhandener Patient wird beim Wiederimport aus dem Schreib-Bundle entfernt
und erscheint deshalb nicht erneut in der Transaction-Antwort.

Practitioner lassen sich per ID oder Identifier suchen. In Bruno den
Query-Parameter `identifier` unkodiert als `urn:oid:2.51.1.3|<GLN>` eingeben;
ein bereits kodiertes `%7C` wird sonst eventuell zu `%257C` doppelt kodiert.

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

## Patientendubletten auf zwei FHIR-Servern testen

`fhir-patient-duplicate-test.html` sucht read-only auf lokalem HAPI und
`https://fhir.woess.ch/fhir/`. Der lokale HAPI wird wie die übrigen lokalen
FHIR-Clients über Keycloak (Authorization Code mit PKCE) angesprochen. Für den
externen HAPI lässt sich die Authentifizierung separat konfigurieren
(keine, Basic Auth oder Bearer Token). Zugangsdaten werden nicht gespeichert.

Die Suche kann per Identifier-System und -Wert oder per Nachname, Vorname und
Geburtsdatum erfolgen. Für Identifier stehen AHVN13/NAVS13, EPR-SPID und
Versicherungskartennummer als Auswahl bereit; weitere Systeme lassen sich über
„Eigene URI eingeben“ angeben. Bei einer gemeinsamen Abfrage zeigt die Seite moegliche
Uebereinstimmungen anhand gemeinsamer Identifier oder Name/Geburtsdatum an.
Diese sind manuell zu pruefen; die Seite erstellt, aktualisiert oder loescht
keine Ressourcen. Beide Suchanfragen laufen ueber die Middleware, damit der
Browser keine direkte Verbindung zu den FHIR-Servern und keine CORS-Freigabe
benoetigt. Die Suchdaten werden im Request-Body an die Middleware gesendet,
damit Patientendaten nicht in URL-Query-Strings der Middleware-Zugriffslogs
erscheinen. Der externe Server ist serverseitig ueber `FHIR_EXTERNAL_BASE_URL`
konfiguriert.

Nach genau einem gefundenen, serverübergreifend passenden Patientenpaar kann
die vollständige Patientensicht optional per Klick geladen werden. Die
Middleware ruft auf beiden Servern `Patient/{id}/$everything?_count=500` ab
und folgt allen Seiten. In der gemeinsamen Ansicht werden Ressourcen gleichen
Typs mit gleichem Identifier gruppiert. Die Darstellung orientiert sich an der
EchoSOS-Ansicht: Übersichtszahlen, Ressourcentypen mit Anzahl und fachlich
lesbare klinische Tabellen für Patient, Kontakte, Vitalzeichen, Labor,
Medikationen, Probleme, Allergien, Impfungen und Begegnungen. Abweichende
Feldwerte werden mit ihrer Serverquelle gekennzeichnet. Die fachliche
Zusammenfassung ist wie bei EchoSOS aufklappbar und zeigt Tabellen mit
Spaltenüberschriften. Darunter bleiben alle Ressourcen typweise gruppiert mit
aufklappbaren Details und FHIR-JSON abrufbar.
Zusätzlich wird im Browser ein gemeinsames FHIR-`Bundle` vom Typ `collection`
gebildet, angezeigt und als JSON herunterladbar gemacht. Identische Ressourcen
(ohne serverlokale ID und Meta) werden dort einmal aufgeführt; FHIR-
`Provenance`-Einträge dokumentieren ihre Quellserver. Beobachtungen ohne Identifier werden für die Visualisierung anhand
von Code, Datum, Patientenbezug und Messwert zusammen gruppiert; wenn weitere
Quelldaten abweichen, bleiben beide Originalressourcen im Bundle erhalten.
Der Abruf kann viele sensible Gesundheitsdaten laden und erfolgt deshalb nicht
automatisch.

```text
https://middleware.local.omnilink.ch/fhir-patient-duplicate-test.html
http://localhost:8082/fhir-patient-duplicate-test.html
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

### eRezept & eMediplan Reader fuer PDFs und Bilder

`erezept-emediplan-reader.html` bietet im gleichen Layout den separaten eRezept & eMediplan Reader:

```text
https://middleware.local.omnilink.ch/erezept-emediplan-reader.html
http://localhost:8082/erezept-emediplan-reader.html
```

Die bisherigen Pfade `/qr-reader.html` und `/erezept-reader.html` bleiben als Aliase verfuegbar.

Nach der Dateiauswahl erscheint fuer jede PDF unter "Input auswaehlen" eine
lokale Vorschau mit dem PDF-Viewer des Browsers. Ohne PDF-Viewer bleibt der
Link "PDF separat oeffnen" verfuegbar. Die Vorschau benoetigt keinen Upload.
PNG-, JPEG- und WebP-Dateien werden ebenfalls direkt unter Input als
skalierte Bildvorschau mit einem Link zum separaten Oeffnen angezeigt.
Dateiwechsel und "Leeren" entfernen die Vorschauen und geben die lokalen
Objekt-URLs frei. Leere PDFs und Dateien ueber 30 MB werden nicht eingebettet.

PDFs (alle Seiten), PNG, JPEG und WebP koennen per Dateiauswahl oder
Drag-and-drop geladen werden. Die Erkennung erfolgt lokal im Browser, ohne
Dokument-Upload, FHIR-Import, Anmeldung oder persistente Speicherung.
Die versionierten Bibliotheken ZXing-WASM und PDF.js werden von jsDelivr geladen;
Internet ist dafuer erforderlich. Die Seite ist damit nicht vollstaendig offline.
Der Reader benoetigt einen aktuellen Browser mit JavaScript-Modul-Unterstuetzung.
Grenzen: 30 MB pro Datei, 100 Seiten pro PDF und 24 Megapixel pro Bild.
Passwortgeschuetzte PDFs muessen vorher entsperrt werden.

Zusaetzlich liest der Reader den eRezept-Link aus dem XMP-Feld
`xmp:signedChmed` der PDF-Metadaten (Attribut oder Element). Er zeigt diesen
separat mit der Ueberschrift "Metadaten / Link aus unsichtbaren PDF-Metadaten"
und eigener Kopier- und Oeffnen-Funktion an,
auch wenn er mit einem QR-Link identisch ist. Abweichungen werden ausdruecklich
markiert. Weder der Metadaten-Link noch der QR-Inhalt wird dadurch als gueltiges
Rezept bestaetigt. Bilder haben keine solche PDF-Metadaten-Auswertung.

Mehrere erkannte QR-Inhalte werden mit Dateiname und gegebenenfalls Seite
unter "QR / Inhalt aus sichtbarem QR-Code" angezeigt. QR-Ergebnisse sind
gruenlich, Metadaten-Ergebnisse orange hinterlegt.
HTTP(S)-Links koennen nach Pruefung der Zieladresse bewusst in einem
neuen Tab geoeffnet werden; andere Inhalte bleiben Text. Eine eingebettete
Anzeige wird nicht angeboten, da HIN sie blockiert. Es erfolgt kein
automatischer Aufruf. Erst beim Oeffnen eines Links werden enthaltene Daten
an dessen Zielseite uebergeben. Nicht lesbare Dateien und Dateien ohne
erkennbaren QR-Code werden explizit im Status gemeldet. Die Kopierfunktion
benoetigt einen sicheren Browserkontext (HTTPS oder localhost).

#### Medikations-JSON im eRezept & eMediplan Reader

Bei CHMED16A1-Inhalten (direkt im QR-Code oder im Fragment eines
eRezept-Links) und JSON-QR-Inhalten bietet jeder Eintrag:

- **Original-JSON anzeigen**: Base64/GZIP wird mit der Browser-API
  `DecompressionStream` lokal dekodiert. Das Objekt muss `Patient` und
  `Medicaments` enthalten; maximal 5 MB entpacktes JSON sind erlaubt.
- **FHIR-JSON konvertieren**: Sendet erst nach Klick das dekodierte
  Original-JSON an den bestehenden Same-Origin-Endpunkt
  `POST /emediplan/convert`. PDF/Bild und Link-Signatur werden nicht hochgeladen.
  Der bestehende Workflow kann Terminologie- und Refdata-Dienste abfragen.
  Es wird kein Import-Endpunkt aufgerufen und nichts nach HAPI geschrieben.
- Beide Ausgaben werden als aufklappbares JSON angezeigt und koennen
  jeweils als JSON-Datei heruntergeladen werden.

Die Dekodierung prueft weder die eRezept-Signatur noch den aktuellen
Abgabe-/Einloesestatus. Die Linkfunktionen und die Trennung von QR- und
PDF-Metadaten-Link bleiben bestehen. Konvertierungsfehler werden beim
betroffenen Eintrag angezeigt; das originale JSON bleibt verfuegbar.

### EchoSOS-Import

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
