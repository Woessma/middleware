# ADR-005: Clinical Notes Mapping

Stand: 2026-11-24

## Status

Accepted (mit offenen Feinauspraegungen fuer DiagnosticReport)

## Entscheidung

Clinical Notes werden primaer über DocumentReference und Binary umgesetzt.
DiagnosticReport bleibt als optionale, fachlich gesteuerte Ergaenzung.

## Kontext

Klinische Notizen und narrative Inhalte werden primär mit
`DocumentReference` und bei eingebetteten Dokumenten zusätzlich mit `Binary`
abgebildet. `DiagnosticReport` ist keine primäre Notiz-Ressource und wird nur
bei fachlich passender Befundlogik ergänzt.

## Konsequenzen

- DocumentReference speichert Referenzen auf binaere Dokumente oder Narrative
- Zusaetzliche Binary-Ressourcen unterstuetzen eingebettete Dokumente
- DiagnosticReport wird nur dort ergaenzt, wo echte Befundlogik vorliegt
