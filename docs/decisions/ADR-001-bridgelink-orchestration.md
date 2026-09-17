# ADR-001: BridgeLink Orchestration

Stand: 2026-07-29

## Status

Accepted

## Entscheidung

BridgeLink orchestriert.
Middleware transformiert.

## Kontext

BridgeLink soll die zentrale Steuerung und das Routing übernehmen, während
die Python-Middleware Daten aus Quellsystemen in FHIR-respektierende Ressourcen
umwandelt.

## Konsequenzen

- klare Verantwortungsaufteilung
- Middleware bleibt fokussiert auf Transformation und Mapping
- Orchestrator kann unabhängig weiterentwickelt werden
- EPIC-spezifische Feldlogik bleibt in der Middleware gekapselt und muss nicht in BridgeLink dupliziert werden
