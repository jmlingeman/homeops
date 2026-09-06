# database

## postgresql

Shared PostgreSQL for cluster apps (chart `postgresql` 13.2.29, **bitnami** OCI
repo; image `bitnami/postgresql:15.4.0-debian-11-r39`).

- **Credentials**: user `dbadmin` (the `postgres` superuser is disabled);
  password from `postgresql-secrets` sops secret (key `password`) via
  `auth.existingSecret` → connects with
  `postgresql://${database_postgresql_username}:<pw>@postgresql.database.svc:5432/<db>`.
- **Storage**: 10Gi PVC on `openebs-hostpath` (pre-created in `app/pvc.yaml`,
  referenced as `existingClaim` — note: not Longhorn, and not replicated).
- **Ingress**: `postgres.${SECRET_DOMAIN}` class `internal` (DNS only; the service
  port is 5432 and the real clients are in-cluster).
- **Consumers**: `piped` (db `piped`, user from its own secret),
  `firefly-iii` (db from its sops secret), …
- **Kustomization**: `cluster-apps-postgresql`, `dependsOn: [external-dns]`
  (so its ingress DNS exists first).
