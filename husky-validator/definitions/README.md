# CDA-Pruefdefinitionen

Dieser Ordner wird read-only nach `/definitions` gemountet. Er enthaelt
bewusst noch keine als passend bestaetigten Profil-Schematrons.

Der Dienst verwendet das CDA-R2-XSD aus `husky-common-gen:3.5.0`.
Fuer eine vollstaendige Pruefung werden zusaetzlich administrativ
bereitgestellte, versionierte, vorab kompilierte Schematron-XSLTs benoetigt:

- `epic-ccda.xsl`: passende C-CDA-Regeln fuer die deklarierten Templateversionen.
- `at-arztbrief.xsl`: Regeln fuer `1.2.40.0.34.6.0.11.0.5.0.3`.

Vor Installation Herkunft, Release, Lizenz, Templatezuordnung und alle
Abhaengigkeiten dokumentieren und mit den lokalen Beispielen testen.
XSLTs muessen eigenstaendig sein: keine Includes/Imports, externen
Dokumente, Textdateien oder Collections. Schematron-Kompilierung findet
nicht waehrend klinischer Requests statt.
Keine Regeln allein anhand von realmCode CH/AT auswaehlen. Kein
automatischer Download bei klinischen Requests.

Fehlende Regeln erzeugen bei `level=full` einen ausdruecklichen
`not-supported`-Fehler, auch wenn die XSD-Pruefung erfolgreich ist.
`level=xsd` ist ausschliesslich eine Strukturpruefung.

Offizielle Quellen fuer die weitere Auswahl:

- [HL7 CDA R2](https://github.com/HL7/CDA-core-2.0)
- [HL7 C-CDA](https://github.com/HL7/C-CDA)
- [ELGA CDA-Schematron](https://gitlab.com/elga-gmbh/cda/schematron/cda-gesamt-schematron)

Das ELGA-Gesamtpaket enthaelt dokumenttypspezifische Regeln. Es ist nicht
ohne Zuordnungspruefung gleichbedeutend mit dem hier erkannten Arztbrief.
Ebenso prueft ein C-CDA-Regelsatz nicht automatisch Schweizer CDA-Profile.
