# Middleware intern: Verarbeitung und FHIR-Transaktion (TX)

Dieses Diagramm zoomt in die FHIR Middleware hinein und zeigt, welche internen
Komponenten bei einem Convert- oder Import-Use-Case (CDA, HL7v2, eMediplan, UMZH, ...)
zusammenarbeiten. Die Middleware erzeugt und validiert das Transaction-Bundle;
BridgeLink fuehrt den Write gegen den FHIR-Server aus. Es ergaenzt [SEQUENZDIAGRAMM-BRIGHT-LINK.md](SEQUENZDIAGRAMM-BRIGHT-LINK.md),
das die Aussensicht von Bright-link auf die Middleware beschreibt.

```mermaid
sequenceDiagram
    participant BrightLink as Bright-link
    participant Middleware as FHIR Middleware
    participant Parser as Parser<br/>(CDA / HL7v2 / eMediplan / UMZH)
    participant Terminology as Terminology Service<br/>(LOINC, SNOMED, CVX, CH-Term, OID)
    participant Builder as Mapper / Builder<br/>(Domain -> FHIR Resource)
    participant Duplicate as Duplicate Service
    participant FHIR as FHIR Server

    BrightLink->>Middleware: Quelldaten mit Bearer JWT (z.B. /cda/import)
    Middleware->>Parser: Rohdaten parsen
    Parser-->>Middleware: Domain-Objekte (Patient, Encounter, Observation, ...)

    Middleware->>Terminology: Codes und Systeme aufloesen
    Terminology-->>Middleware: Gemappte Codings

    Middleware->>Builder: Domain-Objekte + Codings in CH-Core Ressourcen wandeln
    Builder-->>Middleware: FHIR Ressourcen

    Middleware->>Middleware: Bundle stabilisieren<br/>(Requests ergaenzen, Bundle.type -> transaction)

    Middleware->>Duplicate: Ressourcen auf fachliche Duplikate pruefen
    Duplicate->>FHIR: Bestehende Ressourcen abfragen (GET Search)
    FHIR-->>Duplicate: Treffer
    Duplicate-->>Middleware: Duplikate markiert / entfernt

    Middleware-->>BrightLink: FHIR Transaction Bundle
    BrightLink->>FHIR: TX: FHIR Transaction Bundle (POST /fhir)
    FHIR-->>BrightLink: Transaction Response (Ergebnis je Entry)

    alt Transaction erfolgreich
        BrightLink-->>Middleware: Import Ergebnis (angelegte/aktualisierte IDs)
        Middleware-->>BrightLink: Import Ergebnis
    else Transaction fehlgeschlagen
        BrightLink-->>Middleware: Fehlerdetails je Bundle-Entry
        Middleware-->>BrightLink: Fehlerdetails je Bundle-Entry
    end
```

## Beteiligte Komponenten

| Komponente | Aufgabe |
| --- | --- |
| Bright-link | Ruft die Middleware mit Bearer JWT auf, schreibt deren Transaction-Bundle nach HAPI und liefert das Ergebnis zurueck. |
| Parser | Wandelt CDA/HL7v2/eMediplan/UMZH-Rohdaten in Domain-Objekte (`app/parser`, `app/domain`). |
| Terminology Service | Loest Codes gegen LOINC, SNOMED, CVX, CH-Term und OID auf (`app/terminology`). |
| Mapper / Builder | Erzeugt CH-Core-konforme FHIR-Ressourcen aus Domain-Objekten (`app/mappers`, `app/builders`). |
| Duplicate Service | Prueft vor dem Import bestehende FHIR-Ressourcen auf fachliche Duplikate (`fhir_duplicate_service.py`). |
| FHIR Server | Fuehrt die von BridgeLink gestartete Transaktion (TX) aus und persistiert die Ressourcen. |

TX bezeichnet hier das FHIR Transaction Bundle (`Bundle.type = transaction`), das
die Middleware nach Stabilisierung und Duplikatpruefung an BridgeLink zur
Weiterleitung an den FHIR-Server zurueckgibt; der FHIR-Server beantwortet jeden
Bundle-Entry einzeln.
</content>
