# ADR-002: HAPI FHIR as Source of Truth

Stand: 2026-11-24

## Status

Accepted

## Entscheidung

HAPI FHIR ist Source of Truth.

## Kontext

Die FHIR-Instanz ist der zentrale Speicher für medizinische Ressourcen.
Standardimporte werden von der Middleware vorbereitet und durch BridgeLink
nach HAPI FHIR geschrieben. Die Middleware liest HAPI-Metadaten für
Dublettenprüfung und Lookup. Dedizierte Sendepfade wie UMZH und CH-VACD
übertragen validierte Bundles an ein konfiguriertes externes FHIR-Ziel.

## Konsequenzen

- HAPI FHIR dient als autoritative Datenbasis
- Duplikate müssen vor Import reduziert werden
- Middleware benötigt zuverlässige HAPI-Integration
- Import/Export-Qualitaet wird ueber Re-Import-Tests abgesichert (CDA -> FHIR -> CDA)
