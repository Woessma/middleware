# ADR-003: Layered Architecture

Stand: 2026-07-29

## Status

Accepted

## Entscheidung

Parser, Domain, Mapper und Builder bleiben getrennte Schichten.

## Kontext

Eine schichtbasierte Architektur fördert bessere Testbarkeit, Wartbarkeit und
klarere Verantwortlichkeiten.

## Konsequenzen

- Parser extrahiert Rohdaten aus CDA/HL7v2
- Domain Layer modelliert klinische Daten
- Mapper übersetzt Domänenobjekte in FHIR
- Builder erzeugt konkretisierte FHIR-Ressourcen
- Export-Services erzeugen EPIC CDA aus FHIR mit separaten, testbaren Hilfsfunktionen
