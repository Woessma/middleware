# HAPI FHIR: Master Data Management (MDM)

Stand: 2026-11-26 · HAPI FHIR 8.12.0 · Regelversion `ch-golden-v1`

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
Linkantworten mit doppelten Links oder Pflichtfeldern, ungültigen Referenzen
oder einer weiteren Ergebnisseite werden abgelehnt. Die Quellenliste wird
zusätzlich über die jeweilige eindeutige Rückverknüpfung geprüft.
Die zusätzliche Ablehnung unvollständiger oder fehlerhaft paginierter
`$mdm-match`-Antworten ist im Repository implementiert, aber noch nicht deployt.

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
Golden-Referenz erkannt werden und umgekehrt. Ist der Treffer nicht eindeutig, bleibt
es bei `409`. Der geprüfte Wiederholungsimport lieferte 53 Updates
(`200`), keine Neuanlagen (`201`) und keine Stammdaten-Schreibvorgänge.
Derselbe MDM-bewusste Procedure-Abgleich gilt auch für die Konvertierung
im externen VACD-Versand (`/cda/vacd/send`); Konflikte antworten dort
ebenfalls mit `409` statt `500`.

`/cda/prepare` ergänzt den Patient-Eintrag eines neuen Importbundles um einen
stabilen technischen Marker, abgeleitet aus genau einem freigegebenen
EPIC-System/Wert-Paar. Für `LUKS_TEST` ist dies
`urn:oid:1.2.840.114350.1.13.521.3.7.3.688884.100`. Fehlende oder mehrdeutige
Kennungen erfordern Prüfung; ein Konflikt wird als `409` gemeldet. Der Marker
ist pseudonym, nicht anonym. `/cda/convert` bleibt unverändert, und bei einem
bereits gematchten Patienten wird keine Stammdatenressource ergänzt oder
geschrieben. `/cda/prepare` schreibt weiterhin nicht nach HAPI; BridgeLink
führt den anschliessenden Bundle-Write aus. Eine Projektion dieses Markers
oder anderer Source-Identifier auf den Golden Patient ist im separaten
HAPI-Erweiterungsmodul implementiert und isoliert geprüft, aber noch nicht
deployt oder zum Lesen freigegeben.

### Identifier-Übernahme in Vorbereitung

HAPI übernimmt zusätzliche Source-Identifier derzeit nicht automatisch auf
den Golden Patient. Die geplante Synchronisierung soll nur bestätigte Quellen
einbeziehen und Herkunft sowie Änderungen, Unlink, Merge und Löschung
berücksichtigen. Auch bestehende Patienten sollen einbezogen werden. Convert
und Prepare bleiben schreibfrei; die technische CDA-Quelle gehört in einen
späteren Schreibpfad.

Isolierte Experimente untersuchen eine transaktionale PostgreSQL-Outbox,
Wiederanlauf und eine gezieltere Patient-/MDM-Sperrstrategie. Ein vollständiger
Capture- und Lesevertrag für direkte HAPI-REST-/MDM-Zugriffe und BridgeLink
fehlt noch; die bisherigen Tests sind keine Produktionsfreigabe. Das separate
Modul `hapi-mdm-extension/` enthält einen fail-closed Guard für Patient-Reads
und die MDM-Controller-Leseoperationen. In einem isolierten HAPI-8.12-Container
mit synthetischer PostgreSQL-Datenbank wurde geprüft: Patient-POST bleibt bei
`BLOCKED_TEST` erfolgreich (`201`), Patient-GET und -Suche sowie die echte
`$mdm-query-links`-Route antworten mit `503`. Der Controller-Proxy umgeht
interne Aufrufe des globalen `IMdmLinkQuerySvc`. Zwei synthetische Patienten
mit derselben Testkennung erhielten bei `BLOCKED_TEST` jeweils `201`; die
asynchrone HAPI-Verarbeitung erzeugte zwei `mpi_link`-Zeilen. Das bestätigt
nur diesen einfachen Schreibpfad, nicht Wiederanlauf oder alle MDM-Jobs.
MDM-Duplikat- und MDM-Link-Verlaufsrouten wurden nicht als HTTP-Endpunkte
geprüft. Die beiden HAPI-MDM-Bulk-Export-Expander prüfen vor `expandGroup` und
`expandPatient` ebenfalls den Status. Die REST-Einstiege fuer System-/Patient-/
Group-Exporte und deren Statusabfrage sind inzwischen bei gesperrtem Status
geprueft; das ist keine Freigabe der asynchronen Pipeline oder alter Downloads.
Im Erweiterungsmodul liegt nun eine versionierte PostgreSQL-V001-Migration:
Sie erfasst Patient-/History-/Tag-/Provenance- und MDM-Link-Änderungen
transaktional, reiht einen vollständigen Bestandsabgleich als Bootstrap-Job
ein und bietet persistente Claims mit Lease, Fence und begrenzten Retries.
Sie schreibt keine FHIR-Payloads und besitzt absichtlich weder erfolgreiche
Job-Bestätigung noch `READY`-Freigabe. Die Migration wird nicht automatisch
beim HAPI-Start ausgeführt; sie benötigt ein Wartungsfenster ohne Schreiber.
Die reproduzierbare isolierte Prüfung steht in
[hapi-mdm-extension/README.md](../hapi-mdm-extension/README.md).
Der vollständige Testlauf bestand mit 17 Integrationstests ohne Skips.
Er prüfte auch den Erhalt eines Jobs samt Lease bei geordnetem
PostgreSQL-Neustart. Mit der echten V001-Funktion und dem aktuellen Guard
blieben Patient-POST (`201`), -PUT (`200`) und asynchrone MDM-Link-Erzeugung
möglich; Patient-GET, -Suche, -History und `$mdm-query-links` lieferten bei
`BLOCKED_CAPTURE_ONLY` jeweils `503`. Dies ist keine Crash-/Restore-Abnahme
und allein kein Nachweis einer fertigen Golden-Projektion.

V002 ergänzt jetzt einen standardmässig deaktivierten Golden-Identifier-
Projektor: vollständiger Source-/MATCH-Abgleich unter begrenzten Sperren über
den sieben Inputtabellen, versionsqualifizierte HAPI-DAO-Updates und atomare
Bestätigung des einzelnen Outbox-Jobs mit unveränderlichem Receipt.
Die Projektion ist auf 1000 Patient-Zeilen und eine vollständige MATCH-Seite
mit höchstens 1000 Links begrenzt. Ein separat aktivierbarer automatischer
Worker ist implementiert; einen produktiven Steuerendpunkt gibt es nicht.
Auch nach vollständigem Drain
bleibt die Lesesicht mit `BLOCKED_READER_NOT_PUBLISHED` gesperrt.

Die echten HAPI-Prüfungen zeigen Identifier-Ergänzung/-Änderung, NO_MATCH,
Löschung, No-op-Konvergenz, Receipt-Replay nach verlorener Antwort und
gemeinsamen Rollback von Golden-Update und Ack bei Abschluss-/Commitfehlern.
Der aktuelle vollständige Lauf bestand mit 72 Tests ohne Fehler oder Skips:
27 V001-Integrationstests, 23 Reconciler-/Manual-Policy-/Worker-Unit-Tests,
21 V002-Projektor-/Recovery-/Merge-Prüfungen und ein automatisches Worker-Szenario.
Konkurrierende Source-/Link-Schreiber warten auf den Snapshot. Ein wartender
HAPI-Link-Schreiber kann danach einen Versionskonflikt erhalten und benötigt
einen frischen Versuch. Die grobe Tabellensperre ist keine Verfügbarkeits- oder
Performancefreigabe.

Der Worker bleibt standardmässig aus. Zusätzlich zum Projektor benötigt er
`omnilink.mdm.projection.worker.enabled=true`; die laufende Laborkonfiguration
wurde nicht geändert. Er verarbeitet seriell höchstens einen Job pro Tick
(eine Sekunde Pause), nutzt eine 30-Sekunden-Lease und plant bestätigte
Fehlversuche mit fünf Sekunden Abstand erneut ein. Nach fünf Claims oder bei
unaufgelöstem Capture bleibt die Verarbeitung zur Prüfung gesperrt.

Bei unklarem Apply-Ausgang sperrt eine separate Recovery-Transaktion den Job
und prüft anschliessend das Receipt mit einem frischen SQL-Snapshot. Ein
bereits bestätigter Commit wird nicht als Fehler zurückgeschrieben. Nur eine
weiterhin eigene, lebende Lease ohne Bestätigung darf in den Retry-Zustand
wechseln. Unklare Claim-/Recovery-Antworten werden nicht blind wiederholt.
Im isolierten Harness wurde der automatische HAPI-Worker während des
Abschlusses hart beendet: Lease und fehlendes Ack blieben nachweisbar;
nach Neustart wurde der Job mit neuem Fence abgeschlossen. Ein erzwungener
Dauerfehler führte zum begrenzten Retry-Ausschöpfen ohne falschen Golden-Write
oder Leserfreigabe. Das ist keine Datenbank-Crash-/Restore-Abnahme.

Gemäss der gewählten Policy werden explizit manuell gepflegte Golden-Kennungen
gezielt geschützt; Quellkennungen bleiben quellengebunden. Ein separater
global registrierter Schreibinterceptor erhält bereits als manuell markierte
Identifier samt Metadaten auch beim nativen HAPI-NO_MATCH-Neuaufbau. Der
Read-Guard wird dafür nicht globalisiert. Manuelle Kennungen können über einen
kontrollierten internen Java-Schreibkontext markiert, geändert und entfernt
werden. Ein produktiver Editor/Steuerendpunkt wurde nicht ergänzt; öffentliche
Golden-PUTs bleiben durch HAPI mit `403` gesperrt.

Normale Golden-Merges und Merges mit manuell vorgegebenem Ziel-Payload sind
jetzt mit der echten HAPI-Implementierung geprüft. Ein auf den synchronen
Merge begrenzter interner Kontext überträgt ausschliesslich bereits
klassifizierte manuelle Kennungen auf den verbleibenden Golden. Er prüft
gespeicherte IDs/Versionen, erlaubt den nativen Zwischenschritt der reinen
Golden-Tag-Entfernung und wird auch bei Fehlern aufgeräumt. Konflikte zwischen
manueller Ownership, nativen Kennungen oder Metadaten werden vor den
delegierten Merge-Schreibvorgängen abgewiesen, nicht automatisch aufgelöst.

Die MATCH-Quellen werden dem Ziel-Golden zugeordnet; gemeinsame projizierte
Kennungen erhalten zusammengeführte Quellprovenienz. Ein anschliessendes
echtes NO_MATCH entfernt nur den gelösten Quellbeitrag; die verbleibende
Quelle und beide manuellen Golden-Kennungen bleiben erhalten. Wenn HAPI beim
Neuaufbau die Extensions eines weiterhin vorhandenen, zuvor verwalteten
Schlüssels verliert, bleibt dessen bekannte Ownership erhalten. Der nächste
Projektionslauf setzt die Provenienz auf die aktuell bestätigten Quellen.
Unklassifizierte Altkennungen werden dadurch nicht übernommen.

Bestehende unklassifizierte Kennungen werden nicht pauschal als manuell
übernommen und benötigen vor dem Rollout eine explizite Zuordnung. HAPI kann
solche unklassifizierten Werte beim Neuaufbau weiterhin entfernen. Beim Löschen
der letzten Quelle kann der verwaiste Golden entfallen; gelöschte Ressourcen
werden nicht wiederhergestellt. HAPIs Merge-Metadatenpfad kann separate
Transaktionen enthalten: Konkret war die native Duplikat-Link-Löschung mit
`REQUIRES_NEW` ein nachgewiesener Teil-Commit bei späterem Merge-Fehler.
Ein gezielter Adapter führt diese Löschung ausschliesslich innerhalb des
geschützten Patient-Merge-Kontexts in der bestehenden Transaktion aus.
Ausserhalb dieses Kontexts bleibt der native Transaktionspfad unverändert.

Fehler nach dem nativen Merge und beim verzögerten Commit rollen nun beide
Golden-Snapshots samt Tags, sämtliche Links und Capture-Ereignisse gemeinsam
zurück, auch bei vorhandenen Duplikat-Links. Ein frischer Versuch gelingt.
Bei absichtlich verlorener Antwort nach erfolgreichem Commit bleibt der
Redirect bestehen; eine blinde Wiederholung wird ohne weitere Datenänderung
abgewiesen. Parallelitätsfälle, Abbruch während eines Merges, History-Rewrite
und echte Datenbank-/Restore-Fehler benötigen weiterhin eigene Abnahmen.

Der REST-Leseschutz prüft bekannte Patient-Leseoperationen zusätzlich vor
der Handler-Ausführung. Damit liefern auch leere Suchen und reine Zählabfragen
(`_summary=count`, `_count=0`) bei gesperrtem Projektionsstatus `503`.
Auch die systemweite History wird vorab geprueft. Die echten System-/Patient-/
Group-`$export`-Einstiege sowie GET-/POST-`$export-poll-status` liefern bei
gesperrtem Status `503`, ohne einen Exportjob einzureihen. DELETE zur
Export-Stornierung bleibt beim nativen Handler; geprueft ist dessen
`404` fuer eine nicht vorhandene Test-Job-ID, nicht eine echte Stornierung.

Reine Source-Schreib-Bundles funktionieren wieder: Native Schreib-Unteraufrufe
erben zwar BATCH/TRANSACTION, werden aber anhand ihres nativen Unteraufruftyps
und HTTP-Schreibverbs erkannt. Das gibt nachfolgende GETs nicht frei.
In gemischten Bundles liefert HAPI die gesperrte Zaehlabfrage als einzelnen
`503`-OperationOutcome ohne Ressource/Count innerhalb einer HTTP-`200`-Antwort;
vorherige Schreibvorgaenge koennen dabei nativ bereits committen. Der aeussere
HTTP-Status allein belegt deshalb keinen erfolgreichen eingebetteten Read.
Bedingte Creates duerfen vorhandene Sources weiterhin zurueckgeben, jedoch
keine vorhandenen Goldens oder Golden-Redirects am Guard vorbeischleusen.
Nachgelagerte native Antwort-Callbacks erhalten ebenfalls eine transaktionale
Statuspruefung statt eines Fehlers wegen fehlender Transaktion.

Dieser Vorabcheck ist keine konsistente Leserfreigabe über Suche, Cache,
Paging oder asynchrone Exporte hinweg. Insbesondere sind bestehende
Exportdateien/direkte Binary-Downloads und die Zusammensetzung mehrerer
Middleware-Abfragen noch nicht abgesichert. Es gibt weiterhin kein `READY`.

Insbesondere sind ausstehende oder fehlgeschlagene Projektionen nicht als
aktuell auszugeben. Operative Freigabe und Behandlung erschöpfter/
unaufgelöster Jobs, tatsächlich ausgeführter Labor-Bestandsabgleich,
vollständige Leserabdeckung samt
Veröffentlichungsgrenze, Merge-Parallelitätsabnahme sowie Restore-/Deployment-Rollback
fehlen weiterhin. **Die Identifier-Übernahme ist weder fertig noch deployt.**

Arbeitsstand und nächste Schritte für den 2026-11-27:
[Tagesabschluss und Wiedereinstieg](project-memory.md#tagesabschluss-2026-11-26-mdm-arbeitsstand-und-wiedereinstieg).

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
