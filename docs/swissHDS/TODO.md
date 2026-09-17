ka

# SwissHDS TODO

Stand: 2026-08-26

## Ziel

LAB1 aus der SwissHDS-Dokumentation als Bruno-Testablauf nachstellen:

```text
Keycloak Login
  -> AuthN-Token
  -> Authorization Service
  -> AuthZ/AuthR-Token
  -> HAOD-Identitaet
  -> Data Product Catalog
  -> Policy-Pruefung
  -> SwissHDS Gateway
  -> FHIR-Daten
```

Testzugangsdaten werden nicht in Git, Bruno-Dateien oder diese Dokumentation aufgenommen.

## LAB1 mit Bruno

- [ ] Bruno-Umgebung `swisshds-lab` anlegen.
- [ ] URLs als Umgebungsvariablen hinterlegen: Keycloak, Authorization, HAOD, Catalog, Policy und Gateway.
- [ ] Secrets ausschliesslich lokal bzw. ueber die Bruno-Secret-Verwaltung setzen.
- [ ] Keycloak-OIDC-Login mit Authorization Code und PKCE testen.
- [ ] AuthN-Token dekodieren und `iss`, `sub`, Ablaufzeit und Rollen prüfen.
- [ ] Authorization Service mit OAuth-2.1-Client-Credentials aufrufen.
- [ ] AuthZ/AuthR-Token sicher als Bearer-Token weiterverwenden.
- [ ] Arzt-Identitaet ueber die IdP-ID im HAOD nachvollziehen.
- [ ] GLN und HDS-Identitaet aus dem HAOD-Kontext dokumentieren.
- [ ] Datenprodukt-Typ über seine FHIR-Profil-URL im Catalog suchen.
- [ ] Datenlieferant und zugehörigen Gateway-Endpunkt ermitteln.
- [ ] Aktive Arzt-Patient-Beziehung im Policy Service einrichten.
- [ ] Positiven Zugriff über den Gateway testen.
- [ ] Negativtest ohne aktive Beziehung durchführen und `403` erwarten.
- [ ] Optional: geblocktes Dokument testen und Zugriff ablehnen lassen.
- [ ] `GET /api/outbound/scan/fhir/{ResourceType}` für mindestens eine FHIR-Ressource ausführen.
- [ ] Responses, HTTP-Status, Gateway-Warnungen und Correlation-Informationen in Bruno prüfen.
- [ ] Screenshots bzw. Export der Bruno-Requests für die LAB1-Abgabe erstellen.

## Bruno-Collection

- [ ] Request-Gruppe `01-keycloak` erstellen.
- [ ] Request-Gruppe `02-authorization` erstellen.
- [ ] Request-Gruppe `03-catalog` erstellen.
- [ ] Request-Gruppe `04-policy` erstellen.
- [ ] Request-Gruppe `05-gateway` erstellen.
- [ ] Gemeinsame Auth-Header und Token-Variablen definieren.
- [ ] Pre-Request- bzw. Post-Response-Skripte nur für nicht-sensitive Token- und ID-Weitergabe verwenden.
- [ ] Tests für `200`, `201`, `401`, `403` und `404` ergänzen.
- [ ] Token und Passwörter vor Export oder Commit aus der Collection entfernen.

## Middleware: LAB1-Unterstützung

### Konfiguration

- [ ] SwissHDS-Konfiguration in `app/config.py` ergänzen.
- [ ] Keycloak Issuer, JWKS-URL, Realm und Client-Konfiguration über Environment Variablen setzen.
- [ ] Authorization-, Catalog-, Policy- und Gateway-URLs konfigurieren.
- [ ] Zielsysteme über Allowlist bzw. feste Ziel-IDs konfigurieren.

### Clients

- [ ] `app/swisshds/keycloak_client.py` für Token- und JWKS-Kommunikation erstellen.
- [ ] `app/swisshds/authorization_client.py` für den Client-Credentials-Flow erstellen.
- [ ] `app/swisshds/haod_client.py` für die Identitätsauflösung erstellen.
- [ ] `app/swisshds/catalog_client.py` für Datenprodukt- und Store-Suche erstellen.
- [ ] `app/swisshds/policy_client.py` für Zugriffsevaluation erstellen.
- [ ] `app/swisshds/gateway_client.py` für FHIR-Abfragen erstellen.
- [ ] Gemeinsame Timeouts, Fehlerbehandlung und Response-Validierung verwenden.
- [ ] Tokens nie in Query-Strings, Logs oder Fehlermeldungen schreiben.

### API und Zugriffsschutz

- [ ] `GET /swisshds/data/{resource_type}` als fachlichen Lesepfad definieren.
- [ ] Eingehende Bearer-Tokens prüfen oder einen klar definierten Token-Forwarding-Modus implementieren.
- [ ] Ressourcen-Typ und Suchparameter validieren.
- [ ] Policy-Entscheidung vor dem Abruf geschützter Patientendaten ausführen.
- [ ] `401` und `403` sauber von technischen Gateway-Fehlern unterscheiden.
- [ ] `destination_base_url` im bestehenden Sendepfad nicht mehr frei vom Request übernehmen.

### Audit und Betrieb

- [ ] Correlation-ID pro LAB1-Anfrage erzeugen und weiterreichen.
- [ ] Authentisierung, Policy-Entscheidung, Datenabruf und Weitergabe auditierbar protokollieren.
- [ ] Personenbezogene Daten und Tokens aus Logs ausschliessen.
- [ ] Retry-Verhalten und Timeouts für SwissHDS-Abhängigkeiten definieren.
- [ ] Health-/Readiness-Prüfungen für die benötigten SwissHDS-Services ergänzen.

## Tests und Abnahme

- [ ] Unit-Tests für Token-Parsing und Ablaufzeitprüfung schreiben.
- [ ] Unit-Tests für Catalog-, Policy- und Gateway-Clients mit HTTP-Mocks schreiben.
- [ ] Bruno-Smoke-Test für den vollständigen LAB1-Ablauf ausführen.
- [ ] Positivfall: berechtigter Arzt sieht die freigegebenen Patientendaten.
- [ ] Negativfall: unbekannter oder abgelaufener Token wird abgewiesen.
- [ ] Negativfall: fehlende aktive Beziehung liefert `403`.
- [ ] Negativfall: unbekanntes Datenprodukt oder nicht erreichbarer Store wird nachvollziehbar gemeldet.
- [ ] Validieren, dass keine Testzugangsdaten in Git enthalten sind.

## Reihenfolge

1. Bruno-Collection für den vollständigen LAB1-Flow fertigstellen.
2. Erfolgreichen und abgewiesenen Gateway-Zugriff dokumentieren.
3. SwissHDS-Clients in der Middleware implementieren.
4. API-Zugriffsschutz, Audit und Betriebsfehler ergänzen.
5. Bruno-Smoke-Test und Middleware-Integrationstest als wiederholbare Abnahme etablieren.
