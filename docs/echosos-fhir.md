# EchoSOS zu FHIR

Stand: 2026-09-10

## Ablauf

1. EchoSOS-QR, Bild oder PKPass wird an `POST /echosos/qr/import` gesendet.
2. Die Middleware sucht den Patienten anhand von Name und Geburtsdatum.
3. Der Patient wird angelegt oder aktualisiert.
4. QR-Daten wie Notfallkontakt und Blutgruppe werden als FHIR gespeichert.
5. Danach wird automatisch `Patient/{id}/$everything?_count=500` abgefragt.
6. Die Antwort wird in der EchoSOS-Notfallansicht dargestellt.

Der QR-Import und die manuelle Patientensuche verwenden damit denselben
FHIR-Gesamtdatenbestand.

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
  "https://fhir.woess.ch/fhir/Patient/{id}/$everything?_count=500"
```

Die Antwort enthält Patient, `RelatedPerson`, `CareTeam`, `Practitioner`,
`Observation`, `Condition`, `MedicationStatement` und weitere verknüpfte
Ressourcen, sofern sie für den Patienten gespeichert sind.
