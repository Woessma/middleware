# ADR-002: HAPI FHIR as Source of Truth

Stand: 2026-07-29

## Status

Accepted

## Entscheidung

HAPI FHIR ist Source of Truth.

## Kontext

Die FHIR-Instanz soll der zentrale Speicher für medizinische Ressourcen sein.
Diverse Middleware-Transformationen schreiben in HAPI FHIR und lesen deren
Metadaten für Dublettenprüfung und Lookup.

## Konsequenzen

- HAPI FHIR dient als autoritative Datenbasis
- Duplikate müssen vor Import reduziert werden
- Middleware benötigt zuverlässige HAPI-Integration
- Import/Export-Qualitaet wird ueber Re-Import-Tests abgesichert (CDA -> FHIR -> CDA)
