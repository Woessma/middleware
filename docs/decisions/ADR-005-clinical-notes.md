# ADR-005: Clinical Notes Mapping

Stand: 2026-07-29

## Status

Accepted (mit offenen Feinauspraegungen fuer DiagnosticReport)

## Entscheidung

Clinical Notes werden primaer über DocumentReference und Binary umgesetzt.
DiagnosticReport bleibt als optionale, fachlich gesteuerte Ergaenzung.

## Kontext

Um klinische Notizen und narrative Inhalte als FHIR-konforme Ressourcen abzubilden,
sollen DocumentReference und DiagnosticReport als primäre Ressourcen genutzt
werden.

## Konsequenzen

- DocumentReference speichert Referenzen auf binaere Dokumente oder Narrative
- Zusaetzliche Binary-Ressourcen unterstuetzen eingebettete Dokumente
- DiagnosticReport wird nur dort ergaenzt, wo echte Befundlogik vorliegt
