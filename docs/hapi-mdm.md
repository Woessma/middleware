# HAPI FHIR: Master Data Management (MDM)

Stand: 2026-11-20 · HAPI FHIR 8.12.0 · Regelversion `ch-golden-v1`

## Betrieb

HAPI verwaltet Golden Records für `Patient`, `Practitioner` und
`Organization`. Der HAPI-Compose-Dienst setzt `hapi.fhir.mdm_enabled=true`
und lädt `file:/app/config/mdm-rules.json` aus der schreibgeschützt
eingebundenen Datei `/opt/docker/hapi-fhir/mdm-rules.json`. Diese
Laufzeitkonfiguration liegt ausserhalb des Middleware-Repositories.

- Patient: Ein passender AHVN13-, EPIC- oder LUKS-Identifier kann einen
  `MATCH` ergeben. Ähnliche Namen plus Geburtsdatum allein ergeben nur
  `POSSIBLE_MATCH`. Vor Produktiveinsatz die konfigurierten
  EPIC-/LUKS-Identifier-Systeme gegen die echten Quellsysteme prüfen.
- Practitioner und Organization: GLN kann einen `MATCH` ergeben; Namen
  allein liefern höchstens `POSSIBLE_MATCH`. Die Kandidatensuche filtert
  bei diesen Typen auf `active=true`, bei `Patient` nicht.
- Beim Ändern der Regeln in HAPI 8.12 `candidateSearchParams[].searchParams`
  als Array angeben. Die Versionskennung muss in die bestehende
  Datenbankspalte `mpi_link.version` (`VARCHAR(16)`) passen.
- `$mdm-submit` verarbeitet Bestand asynchron und kann Golden Records
  erzeugen. Das ist kein Lesezugriff: Nur nach Freigabe ausführen und
  anschliessend die erzeugten Links kontrollieren. Im initialen Lauf
  entstanden zwölf separate Golden Records für zwölf Quellpatienten;
  es wurden keine unterschiedlichen Patienten zusammengeführt.

## Importentscheidung

Die Middleware fragt die serverweite Operation `POST /$mdm-match` mit
`resource` und `resourceType` ab. `GET /$mdm-query-links` löst bestätigte
Quell-IDs (`resourceId`) auf und listet Quellen eines Golden Record
(`goldenResourceId`). Beide Abfragen ändern keine MDM-Links.

| Ergebnis | Verhalten |
|---|---|
| Sicher, genau eine Golden ID | Golden Record referenzieren; eingehende Stammdaten nicht erneut ins Schreibbundle aufnehmen. Bestätigte Quellen derselben Golden ID zählen als ein Treffer. |
| Möglich, mehrere Golden IDs oder keine eindeutige Golden-Zuordnung | HTTP `409`. Keine willkürliche Auswahl und kein Schreibbundle aus diesem Konflikt. |
| Kein Treffer | Neuanlage im normalen Importpfad. Beim CDA-Pfad gelten zuvor die expliziten EPIC-Fallbacks für Practitioner und Organization. |
| MDM-Abfrage fehlgeschlagen oder Antwort ungültig | Importvorbereitung bricht ab; ein Ausfall wird nicht als «kein Treffer» behandelt. |

### CDA

BridgeLink ruft für `POST /v1/cda/import` die Middleware-Vorbereitung
`/cda/prepare` auf und schreibt erst das erfolgreiche Transaction-Bundle.
`/cda/convert` bleibt eine Konvertierung ohne Write. Die drei
Stammdatenidentitäten werden vor dem klinischen Mapping geklärt. Ohne
MDM-Treffer sind als exakter `System|Wert`-Fallback nur zugelassen:

- Practitioner: `urn:oid:1.2.840.114350.1.13.521.3.7.2.836982`
- Organization: `urn:oid:1.2.840.114350.1.13.521.3.7.2.688879`

Dieselbe CDA-Datei behält stabile klinische Import-Identifier, auch wenn
sich die referenzierte Patienten-ID durch MDM ändert. Eine bestehende
Procedure mit Referenz auf eine bestätigte Quelle kann als Gegenstück zur
Golden-Referenz erkannt werden. Ist der Treffer nicht eindeutig, bleibt
es bei `409`. Der geprüfte Wiederholungsimport lieferte 53 Updates
(`200`), keine Neuanlagen (`201`) und keine Stammdaten-Schreibvorgänge.

### EchoSOS: Import und schreibfreie Notfallansicht

- **Import:** `POST /v1/echosos/resolve` bzw. der Browserpfad über
  `/echosos/import` bietet bei prüfbaren möglichen Treffern einen
  Bestätigungsdialog. Erst nach unabhängiger Identitätsprüfung und
  Bestätigung wird das Importbundle für den gewählten Golden Patient
  erstellt. BridgeLink bleibt der Schreibpfad.
- **Lesesicht:** `GET /echosos/fhir/Patient/{id}/$mdm-everything` liefert
  die Akte des Golden Patient plus seiner bestätigten Quellen. Dedupliziert
  wird nach Ressourcentyp und ID. Die gespeicherten FHIR-Referenzen bleiben
  unverändert. Unvollständige Abfragen ergeben keine Teilakte.
- **Notfall-POC:** Die Suche zeigt pro bestätigter Golden ID einen Treffer.
  Bei einem mehrdeutigen QR-Treffer erscheint derselbe Bestätigungsdialog.
  Die Bestätigung erzeugt nur das Notfall-JSON, keinen Import und keinen
  MDM-Link. Das Notfall-JSON enthält keine Impfungen.

Die Review-ID ist einmalig, fünf Minuten gültig und an Scan,
Keycloak-Identität und Verwendungszweck (Import oder Notfall) gebunden.
Abbrechen sendet keine Bestätigung. Siehe [EchoSOS zu FHIR](./echosos-fhir.md)
für die Browser- und API-Abläufe.

## Prüfung und Fehleranalyse

- `409` bei möglichen Treffern: Kandidaten und bestätigte Quell-/Golden-Links
  prüfen. Übereinstimmende Demografie allein ist keine bestätigte Identität.
- `409` bei CDA-Identifiern: Prüfen, ob ein einziger inhaltsgleicher Treffer
  existiert. Vorhandene Dubletten werden durch einen Reimport nicht bereinigt.
- Für einen Wiederholungsimport in Testumgebung die Eintragsstatus und
  Ziel-IDs beider Antworten vergleichen. Für die EchoSOS-Lesesicht Quelle
  und Golden ID getrennt abfragen: Erwartet werden dieselbe Golden ID und
  dieselben klinischen Ressourcen ohne Umschreiben gespeicherter Referenzen.
- Keine Patienten-Payloads, QR-Dateien, Tokens oder realen Identifikatoren
  in Tickets, Logs oder Git aufnehmen.
