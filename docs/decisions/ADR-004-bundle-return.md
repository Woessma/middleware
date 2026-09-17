# ADR-004: FHIR Bundle Return

Stand: 2026-08-27

## Status

Accepted

## Entscheidung

FHIR Bundles werden an BridgeLink zurückgegeben.

## Kontext

Die Middleware erstellt FHIR Bundles aus Quellsystem-Daten und übergibt diese
zur weiteren Verarbeitung an BridgeLink. BridgeLink uebernimmt danach den Write an HAPI FHIR.

## Konsequenzen

- Bundles sind der zentrale Austauschmechanismus
- Importpfade akzeptieren auch einzelne FHIR-Ressourcen und verpacken sie automatisch als Transaction-Bundle
- Dokumentbundles (`Bundle.type=document`) werden vor dem FHIR-Import als Transaction-Bundle vorbereitet
- Fehlende `entry.request`-Angaben werden anhand der Ressource mit `PUT ResourceType/{id}` oder `POST ResourceType` ergänzt
- Middleware kann idempotente Imports unterstützen
- Bei vorhandenen Identifiern aktualisiert die Middleware bestehende FHIR-Ressourcen per `PUT ResourceType/{id}` nach Lookup, statt Query-Conditional-URLs zu verwenden
- Interne Referenzen werden fuer Transaction-Bundles robust auf `fullUrl` umgeschrieben, auch wenn IDs durch Upsert-Lookup gewechselt haben
- Bundle-Dedupe unterscheidet zwischen fachlich unterschiedlichen `POST`-Einträgen und echten Duplikaten
- In-Run-Duplikate werden bevorzugt schon in Mappern reduziert (z. B. Procedure) und zusätzlich auf Bundle-Ebene abgesichert
- BridgeLink bleibt für Orchestrierung und ggf. zusätzliche Validierung zuständig
- Zusätzlich existiert ein UMZH-Sendpfad (`/cda/umzh/send`), der aus einem erzeugten Bundle einzelne Ressourcen zielgerichtet per `PUT ResourceType/{id}` an externe FHIR-Endpoints versendet
