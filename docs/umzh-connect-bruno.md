# CH UMZH Connect per Bruno oder API Call

Stand: 2026-08-19

Diese Vorlagen erzeugen einen minimalen CH UMZH Connect Ablauf:
1. ServiceRequest (Placer)
2. Coordination Task (Fulfiller)

## Profile (R4, 1.0.0-ballot)
- ServiceRequest Profile: http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-servicerequest
- Task Profile: http://fhir.ch/ig/ch-umzh-connect/StructureDefinition/ch-umzh-connect-coordinationtask

## Dateien im Repo
- app/tests/data/umzh-connect/servicerequest.json
- app/tests/data/umzh-connect/task-initial.json

## Bruno Ablauf

### 1) ServiceRequest erzeugen
- Methode: POST
- URL: https://fhir.omnilink.ch/fhir/ServiceRequest
- Header: Content-Type: application/fhir+json
- Body: app/tests/data/umzh-connect/servicerequest.json

Erwartung: 201 Created mit Location wie ServiceRequest/{id}/_history/1

### 2) Task erzeugen
- In app/tests/data/umzh-connect/task-initial.json beide Referenzen setzen:
  - basedOn[0].reference
  - focus.reference
  auf ServiceRequest/{id} aus Schritt 1.

- Methode: POST
- URL: https://fhir.omnilink.ch/fhir/Task
- Header: Content-Type: application/fhir+json
- Body: app/tests/data/umzh-connect/task-initial.json

Erwartung: 201 Created

## cURL Alternative

### ServiceRequest
curl -X POST "https://fhir.omnilink.ch/fhir/ServiceRequest" \
  -H "Content-Type: application/fhir+json" \
  --data-binary @app/tests/data/umzh-connect/servicerequest.json

### Task
curl -X POST "https://fhir.omnilink.ch/fhir/Task" \
  -H "Content-Type: application/fhir+json" \
  --data-binary @app/tests/data/umzh-connect/task-initial.json

## Hinweise
- Falls dein Validator Profil-Warnungen zeigt, muss das Package ch.fhir.ig.ch-umzh-connect#1.0.0-ballot geladen sein.
- Wenn eure Rollen strikt getrennt sind, sollte requester/owner in Task auf Placer/Fulfiller-Organisationen gesetzt werden.

## CDA -> UMZH Convert mit Workflow-Stages

Neuer Middleware Endpoint:

- `POST /middleware/cda/umzh/convert?workflow_stage=initial|updated|completed`
- Optional: `&target=default|sandbox-placer`

Dieser erzeugt aus einer CDA-Datei ein UMZH-Convert-Bundle passend zum Referral-Ablauf:

- `initial`: ServiceRequest + initial Task
- `updated`: ServiceRequest + in-progress Task + Smoking Questionnaire
- `completed`: ServiceRequest + completed Task + Smoking Questionnaire + QuestionnaireResponse

### Bruno Beispiel

1. URL:
  `http://192.168.167.212:9080/middleware/cda/umzh/convert?workflow_stage=initial`
2. Methode: `POST`
3. Auth: Bearer-JWT ueber BridgeLink
4. Body: `multipart/form-data` mit `file=@<deine-cda>.xml`

Fuer die weiteren Stages einfach den Query-Parameter wechseln:

- `workflow_stage=updated`
- `workflow_stage=completed`

Fuer direkte Tests gegen das `umzhconnect-sandbox` Setup kann zusaetzlich gesetzt werden:

- `target=sandbox-placer`

Dann werden absolute Referenzen auf Sandbox-URLs ausgerichtet:

- Ressourcenbasis: `http://localhost:8080/fhir`
- Task requester: `http://localhost:8084/fhir/Organization/HospitalP`
- Task owner: `http://localhost:8084/fhir/Organization/HospitalF`

## CDA -> UMZH Send (Convert + Versand)

Neuer Middleware Endpoint:

- `POST /middleware/cda/umzh/send`

Query Parameter:

- `workflow_stage=initial|updated|completed`
- `target=default|sandbox-placer`
- `destination_base_url=<FHIR Zielbasis>` (z.B. `http://localhost:8080/fhir`)
- optional `outbound_authorization=Bearer%20<token>`

Beispiel:

`http://192.168.167.212:9080/middleware/cda/umzh/send?workflow_stage=initial&target=sandbox-placer&destination_base_url=http://localhost:8080/fhir`

Body:

- `multipart/form-data` mit Feld `file=@<deine-cda>.xml`

Response:

- `convert`: Infos zum erzeugten UMZH-Bundle
- `send`: detaillierter Versandreport pro Ressource (URL, HTTP-Status, Ergebnis)

Hinweis Sicherheit:

- `outbound_authorization` ist fuer schnelle Sandbox-Tests gedacht.
- Fuer produktive Nutzung sollte der Outbound-Token nicht im Query-String, sondern ueber einen Header uebergeben werden.

## Hinweis zum aktuellen Gesamtstand

UMZH- und EPIC-Medikationspfade koexistieren unveraendert.
Die juengsten EPIC-Aenderungen betreffen primär:

- `POST /cda/import` (Medikations-Coding-Erhalt aus CDA `translation`)
- `GET /fhir/medications/epic-cda/from-server?patient_id=<id>&count=100` (strukturierter Medikamenten-Export)
- Produktanreicherung pruefen ueber `MedicationStatement`-Suche mit `_include=MedicationStatement:medication` (Compendium-/Mappingdaten sind auf `Medication`).

## CDA -> CH VACD Immunization Administration

Der Middleware-Endpoint fuer das CH VACD Immunization Administration Document ist:

- `POST /middleware/cda/vacd/convert`

Der Endpoint liefert immer ein FHIR-R4-Dokumentbundle mit:

- `Bundle.type=document`
- Composition als erstem Entry
- CH-VACD-Profilen auf Bundle, Composition und Immunization
- UUID-Identifier und aufgelösten Bundle-Referenzen

Für einen anschliessenden Import muss das Dokumentbundle nicht manuell in ein
Transaction-Bundle umgebaut werden. Die Middleware wandelt `Bundle.type=document`
beim Import automatisch in `transaction` um und ergänzt fehlende Requests anhand
von Ressourcentyp und ID (`PUT` bei vorhandener ID, sonst `POST`).

### Bruno-Aufruf

1. URL: `http://192.168.167.212:9080/middleware/cda/vacd/convert`
2. Methode: `POST`
3. Auth: Bearer-JWT ueber BridgeLink
4. Body: `multipart/form-data` mit Feld `file=@<deine-cda>.xml`

### cURL-Aufruf

```bash
curl -X POST "http://192.168.167.212:9080/middleware/cda/vacd/convert" \
  -H "Accept: application/fhir+json" \
  -F "file=@app/tests/data/CDA-EPIC.xml"
```

Die VACD-Ausgabe filtert nicht relevante generische CDA-Ressourcen. Impfungen werden in der Composition-Section `11369-6` referenziert. Bekannte Impfprodukte erhalten CVX-, SNOMED-CT- und Swissmedic-Codings.

Für die vollständige Validatorprüfung muss `ch.fhir.ig.ch-vacd#1.0.0` zusätzlich zu CH Core und CH Term geladen sein.
