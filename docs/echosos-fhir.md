# EchoSOS zu FHIR

Stand: 2026-09-10

## Ablauf

1. EchoSOS-QR, Bild oder PKPass wird an `POST /echosos/qr/import` gesendet.
2. Die Middleware sucht den Patienten anhand von Name und Geburtsdatum.
3. Der Patient wird angelegt oder aktualisiert.
4. Kompakt codierte QR-Auswahlen werden dekodiert.
5. Patientenkontakte, Blutgruppe, Allergien und medizinische Vorgeschichte werden
   als FHIR gespeichert.
6. Danach wird automatisch `Patient/{id}/$everything?_count=500` abgefragt.
7. Die Antwort wird in der EchoSOS-Notfallansicht dargestellt.

Der QR-Import und die manuelle Patientensuche verwenden damit denselben
FHIR-Gesamtdatenbestand.

## QR-Daten

Die Fragmentparameter des QR enthalten unter anderem:

- `n1`/`p1` bis `n3`/`p3`: bis zu drei Notfallkontakte
- `b`: Index der Blutgruppe, einschliesslich `Unbekannt`
- `a` und `r`: Allergie- und Reaktionsindizes; Reaktionen werden positionsweise
  den ausgewählten Allergien zugeordnet
- `d`: Indizes der medizinischen Vorgeschichte
- `m`: Medikamentenauswahlen
- `o` und `s`: Organspendeangaben ausserhalb bzw. im Schweizer Register
- `i`: sonstiger Freitext

Die Auswahlindizes werden entsprechend der öffentlich ausgelieferten
EchoSOS-Auswahllisten interpretiert. Der QR wird lokal dekodiert; für die
Auswahlwerte ist kein Abruf der persönlichen QR-URL erforderlich.

## Persistierte FHIR-Ressourcen

- `Patient`: Name, Geburtsdatum und bis zu drei Kontakte mit Beziehung `ECON`
- `Observation`: Blutgruppe mit LOINC `882-1`; der Patient ist Performer
- `AllergyIntolerance`: pro Allergie ein Eintrag, SNOMED-Codierung und optionale
  Reaktionsmanifestation; der Patient ist Recorder
- `Condition`: pro Vorgeschichtsauswahl ein Eintrag; der Patient ist Asserter
- `Consent`: bei expliziter Organspende-Zustimmung oder -Ablehnung; der Patient
  ist Patient und Performer

„Keine bekannten Allergien“ wird als SNOMED-CT `716186003` codiert. Die
Sammelauswahlen „Nierenversagen/Dialyse“ und
„Herzschrittmacher/Defibrillator“ werden ohne eindeutige Unterauswahl als
Quelltext gespeichert, damit keine der möglichen Diagnosen unbegründet
behauptet wird. Für nicht eindeutig spezifizierte Allergieauswahlen bleibt der
Originalbegriff erhalten.

Eine explizite Organspende-Zustimmung wird als `Consent.provision.type = permit`,
eine explizite Ablehnung als `deny` gespeichert. Verwendet werden Scope `adr`
und LOINC `42348-3` (`Advance directives`). Ein Schweizer Registereintrag
(`s=0`) gilt als Zustimmung. Ein fehlender Eintrag (`s=1`) ist keine Ablehnung;
„Keine Angabe“ und fehlende Werte erzeugen keinen Consent. Der QR enthält kein
Erklärungsdatum, daher wird keines ergänzt.

Medikamentenauswahlen und „Sonstiges“ werden derzeit zwar aus dem QR dekodiert,
aber noch nicht als eigene FHIR-Ressourcen persistiert.

## Kontaktmodell

Persönliche Kontakte werden doppelt nutzbar modelliert:

- `Patient.contact` ermöglicht die direkte Darstellung am Patienten.
- `RelatedPerson` ist die referenzierbare FHIR-Ressource der Kontaktperson.
- `Patient.contact.relationship` enthält fachliche Beziehungen.
- `ECON` kennzeichnet den Notfallkontakt.
- `HUSB` kennzeichnet den Ehemann.
- Sonstige Kontakte können mit einer passenden Beziehung wie `SPS` und der
  Kategorie `other` gespeichert werden.

Der Hausarzt wird nicht als persönlicher Kontakt gespeichert. Er wird als
`CareTeam.participant` mit Rolle `PCP` und einer Referenz auf `Practitioner`
modelliert. Bei CDA-Reimports bleiben vorhandene PCP-Teilnehmer erhalten,
wenn der neue CDA-Abschnitt keinen PCP enthält.

## Klinische Darstellung

Die fachliche Zusammenfassung zeigt:

- Vitalzeichen aus `Observation.category = vital-signs`
- Labor aus `Observation.category = laboratory`
- Sozialanamnese aus `Observation.category = social-history`
- Medikationen mit Dosierung, Autor, Status und Code
- Probleme, Allergien und Immunisierungen

Unklassifizierte Beobachtungen und `Encounter`-Ressourcen werden im
Notfallüberblick ausgeblendet. Technische Ressourcendetails werden nicht
angezeigt. Patient und fachliche Zusammenfassung sind standardmässig geöffnet.

## Blutgruppe

EchoSOS speichert die kombinierte Blutgruppe mit:

- LOINC `882-1`, `ABO and Rh group [Type] in Blood`
- `valueCodeableConcept`, zum Beispiel `A+` oder `0+`
- Kategorie `laboratory`

Wenn nur Einzelwerte vorhanden sind, werden ABO mit LOINC `883-9` und Rh mit
LOINC `10331-7` in der Anzeige kombiniert.

## Schwangerschaft

Der aktuelle Schwangerschaftsstatus wird als Observation gespeichert:

- LOINC `82810-3`, `Pregnancy status`
- SNOMED CT `77386006`, `Pregnant`
- Kategorie `social-history`

Eine aktive SNOMED-Condition `127364007` (`Primigravida`) kann zusätzlich in
der Problemliste geführt werden.

## Terminologie

LOINC- und SNOMED-Codings werden, soweit vom TX-Dienst unterstützt, gegen
`https://tx.fhir.ch/r4` geprüft. Schweizer Pharmacodes werden mit dem
NamingSystem `https://emediplan.ch/fhir/NamingSystem/pharmacode` gespeichert.
Sie bleiben zusätzlich als Medikamententext erhalten, werden aber nicht als
LOINC- oder SNOMED-Codes gegen TX validiert.

## Beispielabfrage

```bash
curl -H "Accept: application/fhir+json" \
  "https://fhir.omnilink.ch/fhir/Patient/{id}/$everything?_count=500"
```

Die Antwort enthält Patient, `RelatedPerson`, `CareTeam`, `Practitioner`,
`Observation`, `Condition`, `MedicationStatement` und weitere verknüpfte
Ressourcen, sofern sie für den Patienten gespeichert sind.

Die lokalen EchoSOS-Identifier verwenden
`https://fhir.omnilink.ch/fhir/NamingSystem/...`. Bedingte Upserts suchen
zusätzlich anhand des Identifier-Werts, damit bereits gespeicherte Ressourcen
mit dem früheren Identifier-System beim Reimport wiedergefunden werden.
