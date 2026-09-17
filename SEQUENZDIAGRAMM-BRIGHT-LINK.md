# Bright-link Sequenzdiagramm

Dieses Diagramm beschreibt die Zielarchitektur fuer alle Lese- und Schreib-Use-Cases. Bright-link ist der Zugangspunkt, validiert das JWT und prueft die Berechtigung vor jedem Aufruf. Die Middleware verarbeitet und transformiert medizinische Daten, waehrend der FHIR-Server die FHIR-Ressourcen speichert und abfragt.

```mermaid
sequenceDiagram
    actor Person
    participant IDP as Identity Provider
    participant BrightLink as Bright-link
    participant Middleware as FHIR Middleware
    participant FHIR as FHIR Server

    Person->>IDP: Anmeldung und Einwilligung
    IDP-->>Person: JWT Access Token
    Person->>BrightLink: Use Case mit Bearer JWT
    BrightLink->>BrightLink: JWT Signatur, Ablauf und Claims pruefen
    BrightLink->>BrightLink: Berechtigung fuer Patient und Use Case pruefen

    alt JWT ungueltig oder Berechtigung fehlt
        BrightLink-->>Person: 401 Unauthorized oder 403 Forbidden
    else Lesender Use Case
        BrightLink->>Middleware: GET Anfrage mit Kontext und Bearer JWT
        Middleware->>FHIR: FHIR Suchanfrage
        FHIR-->>Middleware: FHIR Bundle oder Ressource
        Middleware-->>BrightLink: Aufbereitete FHIR Antwort
        BrightLink-->>Person: Ergebnis
    else Pure Convert Use Case
        BrightLink->>Middleware: Quelldaten fuer Convert mit Bearer JWT
        Middleware->>Middleware: CDA, VACD, eTOC, HL7v2, eMediplan oder UMZH in FHIR Bundle konvertieren
        Middleware-->>BrightLink: FHIR Bundle ohne Import
        BrightLink-->>Person: Konvertiertes FHIR Bundle
    else FHIR Stabilisierung
        BrightLink->>Middleware: FHIR Ressource oder Bundle mit Bearer JWT
        Middleware->>Middleware: Bundle stabilisieren und Transaction Requests ergaenzen
        Middleware-->>BrightLink: Stabilisiertes FHIR Transaction Bundle
        BrightLink-->>Person: Stabilisiertes Bundle zur Pruefung
    else Convert und an FHIR senden
        BrightLink->>Middleware: FHIR Ressource oder Bundle mit Bearer JWT
        Middleware->>Middleware: Stabilisieren, deduplizieren und Requests setzen
        Middleware->>FHIR: Stabilisiertes FHIR Transaction Bundle
        FHIR-->>Middleware: Transaction Response
        Middleware-->>BrightLink: Import Ergebnis
        BrightLink-->>Person: Import Ergebnis
    else CDA Import
        BrightLink->>Middleware: CDA Dokument mit Bearer JWT
        Middleware->>Middleware: CDA parsen und FHIR Transaction Bundle erzeugen
        Middleware->>FHIR: FHIR Transaction Bundle
        FHIR-->>Middleware: Transaction Response
        Middleware-->>BrightLink: Import Ergebnis
        BrightLink-->>Person: Import Ergebnis
    else HL7v2 Laborimport
        BrightLink->>Middleware: HL7v2 ORU R01 mit Bearer JWT
        Middleware->>Middleware: ORU R01 parsen und Labor Observations erzeugen
        Middleware->>FHIR: FHIR Transaction Bundle
        FHIR-->>Middleware: Transaction Response
        Middleware-->>BrightLink: Import Ergebnis
        BrightLink-->>Person: Import Ergebnis
    else eMediplan Import
        BrightLink->>Middleware: eMediplan mit Bearer JWT
        Middleware->>Middleware: eMediplan in MedicationStatement transformieren
        Middleware->>FHIR: FHIR Transaction Bundle
        FHIR-->>Middleware: Transaction Response
        Middleware-->>BrightLink: Import Ergebnis
        BrightLink-->>Person: Import Ergebnis
    else UMZH Connect
        BrightLink->>Middleware: UMZH Auftrag mit Bearer JWT
        Middleware->>FHIR: Task, ServiceRequest und QuestionnaireResponse
        FHIR-->>Middleware: FHIR Response
        Middleware-->>BrightLink: Auftragsergebnis
        BrightLink-->>Person: Auftragsergebnis
    end
```

## Verantwortlichkeiten

| Komponente | Verantwortung |
| --- | --- |
| Person | Meldet sich an und startet einen Use Case. |
| Identity Provider | Authentifiziert die Person und stellt ein signiertes, zeitlich begrenztes JWT aus. |
| Bright-link | Validiert JWT und Berechtigungen; leitet nur autorisierte Anfragen an die Middleware weiter. |
| FHIR Middleware | Konvertiert CDA, VACD, eTOC, HL7v2, eMediplan und UMZH-Daten; stabilisiert FHIR-Bundles; koordiniert FHIR-Transaktionen und Abfragen. |
| FHIR Server | Persistiert und liefert FHIR-Ressourcen. |
