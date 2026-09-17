# Benoetigte Infrastruktur fuer Kubernetes
Stand: 2026-07-30

## Infrastrukturbedarf

- Ein Kubernetes-Cluster, idealerweise managed: AKS, EKS oder GKE. Fuer PROD realistisch mindestens 3 Worker Nodes verteilt ueber 2 bis 3 Zonen.
- Ein externer Load Balancer plus Ingress Controller fuer fhir.omnilink.ch und spaetere weitere Endpunkte.
- Eine Container Registry fuer versionierte Images mit Scan und Retention.
- Eine PostgreSQL-Plattform.
- Bevorzugt Managed PostgreSQL mit Backups, Failover und Patching.
- Alternativ Kubernetes-intern mit Persistent Volumes, was operativ deutlich aufwendiger ist.
- Persistenter Storage fuer stateful Komponenten und Backups.
- DNS- und Zertifikats-Management, z. B. cert-manager oder Anbindung an bestehende PKI oder Let's Encrypt.
- Secret Management, z. B. Cloud KMS, Vault oder der jeweilige Cloud-Secret-Store.
- Observability: zentrales Logging, Metrics, Alerting, optional Tracing.
- CI/CD-Pipeline fuer Build, Test, Image Push und Deployment nach DEV, TEST und PROD.
- Backup- und Restore-Prozesse, speziell fuer PostgreSQL und Konfigurationen.
- Netzwerk-Anbindung zu BridgeLink und Quellsystemen, je nach Umgebung per VPN, Private Link oder internen Firewalls.
- Rollen- und Rechtemodell: Kubernetes RBAC, Namespace-Trennung, Audit-Logs.

## Management-Hinweis

Der wesentliche Infrastrukturaufwand liegt nicht in der Fachlogik der Middleware, sondern im sicheren und stabilen Plattformbetrieb mit Netzwerk, Security, Datenhaltung, Deployment und Monitoring.