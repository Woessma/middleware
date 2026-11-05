# Interner Husky-CDA-Validator

Additiver Dienst fuer die Validierung des **originalen CDA-XMLs** und die
Erzeugung/Pruefung einer CH-EMED-EPR-FHIR-Vorschau sowie die zusaetzliche
CH-VACD-FHIR-Profilpruefung. Getrennt von bestehenden
CDA-Konvertierungen und HAPI-FHIR-Validierungen. Kein Import,
kein Patientenabgleich, keine externen klinischen Requests.

## Betrieb

```sh
docker compose stop husky-validator
docker compose build husky-validator middleware
docker compose up -d --no-deps husky-validator middleware
```

Java 21, Husky `3.5.0`, kein Snapshot. Der Dienst hat **keinen Hostport**
und kein Proxy-Netz; ausschliesslich das interne Compose-Netz `validation`.
Nur die Middleware ist zusaetzlich an dieses Netz angeschlossen.
`GET http://husky-validator:8091/health` meldet Engine-Version, XSD und
tatsaechlich geladene Schematron-Profile. Fehlende Profilregeln machen den
Basisdienst nicht unhealthy, werden aber bei Vollpruefungen als Fehler
gemeldet. Ungueltige installierte XSLTs verhindern den Dienststart.
Der gemeinsame PMLC-/VACD-Instance-Validator laedt seine festen lokalen IG-Pakete beim Start;
dafuer sind 1536 MiB Java-Heap und ein Containerlimit von 2 GiB konfiguriert.
Die Initialisierung dauert entsprechend laenger als die reine XSD-Pruefung.
Speichermangel beendet Java explizit, damit die Restart-Policy greift und
kein nicht mehr antwortender Prozess verbleibt.
Maven ist beim Build auf 256 MiB Heap begrenzt, der Testprozess auf 1536 MiB.
Auf kleinen Hosts den laufenden Husky-Dienst vor einem Java-Neubau stoppen,
damit nicht zwei warme Validatoren gleichzeitig Speicher belegen.

Requests gehen ueber die Middleware:

```http
POST /cda/source/validate?level=full
Content-Type: application/xml

<ClinicalDocument xmlns="urn:hl7-org:v3">...</ClinicalDocument>
```

Alternativ Multipart-Feld `file` oder Form-Feld `raw_xml`. Maximal 5 MiB
CDA-Inhalt, interner Client-Timeout 5 Sekunden Verbindung / 60 Sekunden
Antwort. Kein frei waehlbares Validierungsziel oder Schema-URL.

- `level=full` (Default): CDA-R2-XSD plus passende Profil-Schematron-Regeln.
- `level=xsd`: nur CDA-R2-Struktur; **kein** Profil-Konformitaetsnachweis.
- Ergebnis: `OperationOutcome` mit `error`, `fatal`, `warning`, `information`.
  HTTP 200 heisst ausgefuehrte Pruefung, nicht Fehlerfreiheit.
- Fehlergruppen tragen die Extension `urn:omnilink:validation:profile`
  mit `valueString`; XML-Felder/XPath stehen in `expression`.
- Fehlende Regeln: `error / not-supported`, keine erfundene Konformitaet.
- Leere Eingabe: 400; zu grosse Eingabe: 413; Dienst-/Enginefehler: Middleware 502.
- Keine automatische Sperre oder Aenderung bestehender Importwege.

## Abdeckung und Herkunft

| Pruefung | Stand |
|---|---|
| CDA R2 XSD | Aktiv, aus `org.projecthusky.common:husky-common-gen:3.5.0`, `schemas/hl7cdar2/CDA.xsd` und lokale Includes |
| EPIC/C-CDA | Dokumenttemplates erkannt; kein exakt passender offizieller Schematron-Satz installiert |
| HL7-AT Arztbrief | Dokumenttemplate erkannt; kein exakt passender offizieller Schematron-Satz installiert |
| CH-EMED-EPR | PMLC-FHIR-Vorschau mit Instance-Validierung, PDF/A noch nicht enthalten |
| CH-VACD | Zusaetzliche Offline-Instance-Pruefung, Immunization Administration 6.0.0 |
| FHIR R4/IGs | Bestehender HAPI-Validator unveraendert; PMLC/VACD mit festem Husky-Paketbestand |

PMLC-Vertrag, Profilversionen und bewusste PDF/A-Luecke:
[CH-EMED-EPR-FHIR-Vorschau](../docs/ch-emed-epr-pmlc.md).

VACD-Vertrag und Paketherkunft:
[CH-VACD](../docs/ch-vacd-immunization-administration.md).
Interner Endpunkt `POST /vacd/validate`, extern ueber die Middleware
`POST /cda/vacd/husky/validate` (XML) oder
`POST /fhir/vacd/husky/validate` (FHIR-JSON).
Keine automatische Aenderung der HAPI-Pruefung oder des Versands.
Die Health-Antwort nennt das geladene `vacdProfile`.

FHIR-Outcomes nennen das angeforderte Dokumentprofil in der Top-Level-
Extension `urn:omnilink:validation:profile`. Eindeutig auf einen Bundle-
Eintrag bezogene Meldungen erhalten zusaetzlich die deklarierten
Ressourcenprofile als `urn:omnilink:validation:context-profile`.
Dies ist Ressourcen-Kontext, keine kausale Einzelprofilzuordnung.
Diagnostik, Severity und Positionen bleiben unveraendert. Die Werkbank
unterscheidet explizite Profilangaben, Ressourcen-Kontext und Prueflauf.
Fuer Contained-Pfade wird kein Elternprofil als Kontext behauptet.

Die technische Untersuchung der lokalen Varianten ergab:

- EPIC: realm CH, aber C-CDA-Templates `2.16.840.1.113883.10.20.22.1.1`
  mit fehlender Extension, `2015-08-01` und `2023-05-01`, sowie
  `2.16.840.1.113883.10.20.22.1.2`. Dies ist **keine** automatische CDA-CH-Zuordnung.
- AT: Arztbrief-Template `1.2.40.0.34.6.0.11.0.5.0.3` sowie allgemeine
  AT-Header-/Dokumenttemplates. Die aktuell untersuchten offiziellen
  ELGA-Entlassungsbriefregeln nennen dagegen eine andere Transaktion
  (`1.2.40.0.34.77.4.102`, Stand `2023-05-09`).
  Ohne belegte Template-/Versionszuordnung werden diese nicht angewendet.

Auch SDTC/andere CDA-Erweiterungen erhalten durch die Basis-XSD-Pruefung
keinen pauschalen Konformitaetsnachweis. Vor Profilfreigabe muessen
Versionskombinationen und erforderliche Terminologiedaten geklaert werden.
Bekannte Erweiterungsnamespaces erzeugen einen zusaetzlichen expliziten
Abdeckungswarnhinweis. Basis-XSD-Abweichungen an solchen Erweiterungen sind
kein belegter Verstoss gegen den jeweiligen Implementierungsleitfaden.
Installationsanforderungen und offizielle Quellen:
[Pruefdefinitionen](definitions/README.md).

Interne Stichprobe am 2026-11-05, ohne Konvertierung/Speicherung:

| Lokales Beispiel | Basis-XSD-Abweichungen | Vollpruefung |
|---|---|---|
| EPIC | 5, jeweils SDTC-Erweiterungen | zusaetzlich fehlende C-CDA-Profilregeln |
| AT | 6, HL7-AT/PHARM/IPS-Erweiterungen | zusaetzlich fehlende Arztbrief-Profilregeln |

Beide Varianten benoetigen passend versionierte Erweiterungsschemas und
Schematron-Regeln, bevor eine echte Profilkonformitaet beurteilt werden kann.

## XML- und Schematron-Isolation

DTD, externe Entities und XInclude sind fuer CDA deaktiviert. XSD-Includes
werden nur aus dem ausgelieferten Schemaordner aufgeloest. Schematrons
werden als eigenstaendige, vorab kompilierte XSLTs installiert und beim
Start geladen; keine Netzdownloads oder Kompilierung im klinischen Request.
XSLT-Includes/Imports und externe Dokument-/Text-/Collection-Zugriffe sind
gesperrt. Die Auswertung ist serialisiert, da die Engine nicht thread-safe
ist. Fehlerlogs enthalten keine CDA-Payloads.

Huskys `SchematronValidator` kapselt seine Resolver. Ein Negativtest zeigte,
dass reine JAXP-Systemproperties externe `doc()`-Zugriffe dort nicht
zuverlaessig sperren. Deshalb verwendet dieser Dienst fuer die Auswertung
die oeffentliche `ph-schematron`-API mit explizit gesperrten Resolvern;
Husky bleibt fuer XSD und Schematron-Report/Kompilierung eingebunden.
Die synthetischen Testschematrons sind **keine** offiziellen Profilregeln.

## Tests und Lizenzen

Getrennte Medikationskorrektur am 2026-11-05: 20 Java-Tests im Docker-Build,
109 Python- und 54 Node-Tests bestanden. Der Ausgabemapper prueft contained Medication,
UUID-Stabilitaet, erhaltene Quell-Identifier in Provenance, UCUM-Einheiten,
PractitionerRole-Verweise und unveraenderte Quellressourcen. Die separate
verpflichtende Importpruefung verwendet den internen HAPI-Server, nicht
den Husky-Ausgabevalidator. Bestehende HAPI-Daten werden nicht migriert.
Middleware und Husky sind neu gebaut und gestartet; das CDA-Gateway
benoetigt noch das [Routingupdate](../bridgelink/README.md).

Der Docker-Build fuehrt die Java-Tests aus. Python-Tests:
`app/tests/test_cda_source_validation.py`, bestehende FHIR-/VACD-Tests;
Werkbanktests pruefen Auswahl, Raw-XML und Profilanzeige.

VACD-Ergaenzung am 2026-11-05: 15 Java-, 51 Python- und 26 Werkbanktests
bestanden. Das unveraenderte offizielle synthetische CH-VACD-6.0.0-Beispiel
liefert im deployten Husky-Validator 0 Fehler und 5 Warnungen; die
Fehlerfreiheit ist als Regressionstest abgesichert. Ein unvollstaendiges
synthetisches CDA wurde ueber Raw-XML, Formular und Datei konvertiert und
mit echten Profilfehlern (422) zurueckgegeben. Kein HAPI-Write oder Versand.

Husky ist unveraendert als Maven-Abhaengigkeit eingebunden, EPL 1.0.
Quellen/Schemahistorie und Lizenz des festgelegten Releases:

- [Husky 3.5.0 Quellcode](https://github.com/project-husky/husky/tree/48639ed3e654edab0e3c1af416516a5694735d0d)
- [Husky Lizenz](https://github.com/project-husky/husky/blob/48639ed3e654edab0e3c1af416516a5694735d0d/License.md)
- [ph-schematron](https://github.com/phax/ph-schematron) (Apache 2.0)

Abhaengigkeiten behalten ihre JAR-Lizenz-/Notice-Eintraege. Bei Weitergabe
von Images muessen deren Lizenz-/Quellcodepflichten separat beruecksichtigt
werden; die Integration ersetzt keine rechtliche Lizenzpruefung.
