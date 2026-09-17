# TODO: Neuaufbau der FHIR-Plattform auf einer neuen VM

Stand: 2026-09-09

Diese Checkliste beschreibt den Neuaufbau von HAPI FHIR, Nginx und optional Matrix/Synapse auf einer neuen virtuellen Maschine. Es werden keine Betriebsdaten uebernommen. Die Python-FHIR-Middleware wird ausschliesslich als Quellcode aus diesem Repository weiterverwendet und frisch gebaut. Die bestehende VM bleibt bis zur erfolgreichen Abnahme unveraendert und dient als Rueckfalloption.

## 1. Planung und Verantwortlichkeiten

[ ] Schriftlich festhalten: Keine Datenmigration, kein Restore und keine Uebernahme von Docker-Volumes, Datenbanken, FHIR-Ressourcen, Dokumenten oder Matrix-Daten.
    Erklaerung: Weiterverwendet wird nur der versionierte Python-Middleware-Quellcode. Zugangsdaten, Zertifikate und Konfigurationen werden fuer die neue Umgebung neu erstellt.

[ ] Wartungsfenster, verantwortliche Personen und einen Kommunikationskanal festlegen.
    Erklaerung: Waehle ein Zeitfenster mit wenig Verkehr. Vor dem Start muss klar sein, wer DNS aendert, wer die Tests durchfuehrt und wer bei Problemen zurueckschaltet.

[ ] DNS-TTL fuer fhir.woess.ch mindestens 24 Stunden vorher auf 300 Sekunden reduzieren.
    Erklaerung: Nach der Umschaltung verbreitet sich die neue IP schneller. Den vorherigen TTL-Wert nach erfolgreicher Migration wieder setzen.

[ ] Rueckfallkriterium und maximale Downtime festlegen.
    Erklaerung: Beispiel: Falls die Abnahmetests nicht innerhalb von 30 Minuten erfolgreich sind, DNS wieder auf die alte VM zuruecksetzen. Die alte VM erst danach stilllegen.

## 2. Ziel-VM vorbereiten

[ ] Aktuelles Linux patchen und Docker Engine mit Docker Compose Plugin installieren.
    Erklaerung: Der Betrieb ist Docker-Compose-basiert. Installierte Versionen mit "docker --version" und "docker compose version" dokumentieren.

[ ] SSH-Zugang absichern und einen separaten administrativen Benutzer verwenden.
    Erklaerung: Passwort-Login deaktivieren, SSH-Keys verwenden und den Root-Login sperren. Der Zugang zur alten VM bleibt bis nach dem Abnahmetest erhalten.

[ ] Firewall einrichten: nur 22, 80 und 443 von aussen freigeben.
    Erklaerung: PostgreSQL, HAPI, Adminer und Synapse duerfen nicht direkt aus dem Internet erreichbar sein. Sie sind im Compose nur intern oder an 127.0.0.1 gebunden.

[ ] Speicher, RAM und CPU passend fuer den geplanten Neubetrieb bereitstellen.
    Erklaerung: PostgreSQL startet leer, braucht aber freien Speicher fuer neue Daten, WAL und Backups.

[ ] Monitoring, Logrotation und automatisierte Off-Host-Backups vorbereiten.
    Erklaerung: Ein Backup auf derselben VM schuetzt nicht gegen VM-Ausfall. Die neue Backup-Kette beginnt ohne Altdaten.

## 3. Quellcode bereitstellen und Konfiguration neu erstellen

[ ] Das Repository auf der Ziel-VM in einer festen Struktur auschecken.
    Erklaerung: Nginx mountet HTML-Testseiten relativ zum FHIR-Server-Verzeichnis. Deshalb muss der gesamte Woess_Fhir-Checkout vorhanden sein, nicht nur ein einzelner Container-Ordner.

[ ] Neue, nicht versionierte Konfigurationen erstellen.
    Erklaerung: Dazu gehoeren insbesondere fhir-middleware/.env mit REFDATA_API_KEY, Matrix-Konfiguration, fhir-server/htpasswd sowie Cron-Konfigurationen. Keine Secrets aus der alten VM kopieren oder in Git ablegen.

[ ] Alle Zugangsdaten neu erzeugen und ihre Gueltigkeit pruefen.
    Erklaerung: Datenbankpasswoerter, Basic-Auth-Benutzer, Matrix-Secrets und API-Keys werden fuer die neue Umgebung neu angelegt und sicher gespeichert.

[ ] Externes Docker-Netz anlegen: "docker network create fhir-server_fhir-net".
    Erklaerung: FHIR-Server, Middleware und optional Matrix-Bot verwenden dieses externe Netz. Ohne das Netz starten die getrennten Compose-Stacks nicht korrekt.

## 4. Leere Plattform starten: Reverse Proxy, DNS und TLS

[ ] Nginx-Konfiguration mit "nginx -t" im Container pruefen und die Compose-Konfiguration mit "docker compose config" validieren.
    Erklaerung: Damit werden Syntaxfehler, fehlende Mounts und falsch interpolierte Umgebungsvariablen vor der Umschaltung erkannt.

[ ] Sicherstellen, dass Port 80 fuer die ACME-Challenge erreichbar ist.
    Erklaerung: Die aktuelle Nginx-Konfiguration bedient /.well-known/acme-challenge/ aus certbot-www. Firewall, DNS und Nginx muessen dazu zusammenpassen.

[ ] TLS-Zertifikat fuer fhir.woess.ch auf der Ziel-VM neu ausstellen.
    Erklaerung: Private Schluessel und Zertifikate der alten VM werden nicht kopiert. Fuer die ACME-Challenge muss Port 80 auf der neuen VM erreichbar sein.

[ ] Nach erfolgreicher lokaler Abnahme den DNS-A-Record auf die neue IP umstellen.
    Erklaerung: Alte VM weiterlaufen lassen, bis externe Anfragen nachweislich die neue VM erreichen. Dann den alten TTL-Wert wiederherstellen.

## 5. Python-Middleware neu deployen und abnehmen

[ ] FHIR-Server-Container und Healthchecks pruefen: "docker compose ps" sowie "docker compose logs --tail=100".
    Erklaerung: Postgres muss gesund sein, bevor HAPI stabil arbeitet. Die Datenbank muss ein neu angelegtes, leeres Volume verwenden.

[ ] Im Verzeichnis fhir-middleware die Konfiguration mit "docker compose config" pruefen und die Middleware mit "docker compose up -d --build" neu bauen und starten.
    Erklaerung: Der Container muss im Netzwerk fhir-server_fhir-net laufen und den FHIR-Server ueber http://fhir-server:8080/fhir erreichen.

[ ] Mit gueltiger Basic Auth "https://fhir.woess.ch/fhir/metadata" aufrufen.
    Erklaerung: Der Aufruf prueft DNS, TLS, Nginx, Authentisierung, Docker-Netz und HAPI als durchgehenden Pfad.

[ ] Einen realistischen Middleware-Test fuer CDA und eMediplan ausfuehren.
    Erklaerung: Ein HTTP-200 allein reicht nicht. Das erzeugte FHIR-Bundle sowie gespeicherte Ressourcen muessen fachlich plausibel sein und bilden die neue Datenbasis.

[ ] Falls aktiviert: Matrix-Bot mit einem neu angelegten Testkonto und einer neuen Patientenidentitaet testen.
    Erklaerung: Dies prueft die frisch initialisierte Synapse-Instanz, Bot-Zugang, Dateiverarbeitung, das gemeinsame Docker-Netz und den Zugriff auf die Middleware.

[ ] Backup der neuen, leeren Ausgangsbasis ausloesen und Wiederherstellbarkeit dokumentieren.
    Erklaerung: Damit endet der Neuaufbau erst, wenn der neue Betrieb auch wiederherstellbar ist.

## 6. Abschluss und Rueckbau

[ ] Beobachtungsphase von mindestens 24 bis 72 Stunden vereinbaren und Fehlerlogs kontrollieren.
    Erklaerung: Probleme mit DNS-Caches, Zertifikatserneuerung oder externen Partnern treten teils erst nach dem Cutover auf.

[ ] Alte VM erst nach der Beobachtungsphase abschalten.
    Erklaerung: Bis dahin bleibt sie eine einfache Rueckfalloption. Danach Zugriffe und Daten gemaess Sicherheits- und Aufbewahrungsvorgaben sicher loeschen oder archivieren.

[ ] Betriebsdokumentation aktualisieren: neue IP, Hostname, Backup-Ort, Verantwortlichkeiten und Zertifikatserneuerung.
    Erklaerung: Diese Angaben verhindern, dass der naechste Eingriff vom Wissen einzelner Personen abhaengt.