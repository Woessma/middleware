# Checkliste: Neuaufbau ohne Datenuebernahme

Stand: 2026-09-09

## Geltungsbereich

Ziel ist ein vollstaendiger Neuaufbau der Plattform. Es werden keine Betriebsdaten
von der bisherigen Umgebung uebernommen. Die Python-Middleware wird als
Quellcode aus diesem Repository weiterverwendet und auf der Zielumgebung neu
deployt.

Nicht uebernehmen:

- HAPI-FHIR- und PostgreSQL-Datenbanken oder deren Docker-Volumes
- FHIR-Ressourcen, Dokumente, Bundles, Uploads und Backups
- Matrix/Synapse-Daten, Raeume, Nachrichten, Medien und Patientenzuordnungen
- TLS-Zertifikate, `.env`-Dateien, Passwoerter, API-Keys und Basic-Auth-Dateien
- Docker-Images, Container, Netzwerke und Laufzeitverzeichnisse der alten VM

## 1. Entscheidung und Inventar

[ ] Schriftlich festhalten, dass keine Datenmigration und kein Restore erfolgen.

[ ] Die alte Umgebung bis zur Abnahme unveraendert und getrennt als Rueckfall- und Referenzsystem belassen.

[ ] Alle benoetigten Komponenten fuer den Neuaufbau festlegen: FHIR-Server, PostgreSQL, Nginx/TLS, Python-Middleware und optional Matrix/Synapse/Bot.

[ ] Externe Abhaengigkeiten erfassen: DNS, Firewall, Docker Registry, refdata.ch, Terminologie-Server sowie benoetigte Benutzer und Rollen.

## 2. Zielumgebung vorbereiten

[ ] Aktuelles Linux patchen; Docker Engine und Docker Compose Plugin installieren.

[ ] Separaten administrativen Benutzer mit SSH-Key einrichten; Root- und Passwort-Login deaktivieren.

[ ] Firewall auf 22, 80 und 443 beschraenken. PostgreSQL, HAPI, Adminer und Synapse bleiben intern oder an `127.0.0.1` gebunden.

[ ] Monitoring, Logrotation und Backups fuer den neuen Betrieb einrichten. Backups beginnen leer und enthalten keine Altdaten.

[ ] Vorhandenes Docker-Netzwerk `proxy` verwenden; kein zweites FHIR-Netz anlegen.

## 3. Code und neue Konfiguration bereitstellen

[ ] Repository frisch auf der Zielumgebung auschecken; keine Arbeitsverzeichnisse oder Dateien von der alten VM kopieren.

[ ] Fuer jeden Dienst neue Secrets erzeugen und sicher ablegen: PostgreSQL-Zugang, Nginx-Basic-Auth, Matrix-Secrets und API-Keys.

[ ] Neue, nicht versionierte `.env` erstellen und den benoetigten `REFDATA_API_KEY` hinterlegen.

[ ] `fhir-server/docker-compose.yml` auf neue Datenbank-Credentials abstimmen; keine alten PostgreSQL-Volumes referenzieren.

[ ] Falls Matrix benoetigt wird, Synapse und Bot mit einer leeren Datenbank und neuen Schluesseln initialisieren. `patient_identities.json` nicht aus der alten Umgebung uebernehmen.

## 4. Leere Plattform starten

[ ] FHIR-Server-Stack starten: im Verzeichnis `fhir-server` den Befehl `docker compose up -d` ausfuehren.

[ ] Sicherstellen, dass PostgreSQL ein neu angelegtes leeres Volume verwendet und gesund ist: `docker compose ps`.

[ ] HAPI-FHIR starten lassen und `http://127.0.0.1:8080/fhir/metadata` lokal pruefen.

[ ] Nginx-Konfiguration mit `docker compose config` und `nginx -t` im Container validieren.

[ ] DNS auf die neue Umgebung umstellen und ein neues TLS-Zertifikat ausstellen. Private Schluessel der alten VM nicht kopieren.

## 5. Python-Middleware deployen

[ ] Im Verzeichnis `/opt/python-middleware` die Konfiguration mit `docker compose config` pruefen.

[ ] Middleware neu bauen und starten: `docker compose up -d --build`.

[ ] Bestaetigen, dass `python-middleware` im Netzwerk `proxy` laeuft und HAPI ueber `http://hapi-fhir:8080/fhir` erreicht.

[ ] Middleware-Logs auf fehlende Secrets, Netzwerkfehler und Terminologie-/refdata-Fehler pruefen: `docker compose logs --tail=100 middleware`.

[ ] Einen CDA- und einen eMediplan-Test gegen die neue Middleware ausfuehren; die dabei erzeugten Ressourcen gelten als neue Datenbasis.

## 6. Abnahme und Abschluss

[ ] Extern `https://fhir.omnilink.ch/fhir/metadata` ueber BridgeLink pruefen.

[ ] Verifizieren, dass die neue FHIR-Datenbank zu Beginn keine Ressourcen aus dem Altsystem enthaelt.

[ ] Optional Matrix/Bot mit einem neu angelegten Testkonto und einer neuen Patientenidentitaet testen.

[ ] Neu erstellte Zugangsdaten, DNS, Zertifikatserneuerung, Backup-Ziel und Verantwortlichkeiten dokumentieren.

[ ] Nach vereinbarter Beobachtungsphase die alte Umgebung gemaess Sicherheits- und Aufbewahrungsvorgaben stilllegen oder loeschen.