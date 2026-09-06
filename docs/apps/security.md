# security

## vaultwarden ⚠️ (registered, but build broken)

[Vaultwarden](https://github.com/vaultwarden/server) — Bitwarden-compatible
password manager (image `docker.io/vaultwarden/server:latest`,
`imagePullPolicy: Always`).

- **Intended shape**: public ingress `bitwarden.${SECRET_DOMAIN}`
  (`className: external` + external-dns target → public through Cloudflare),
  3Gi longhorn `data` PVC at `/data` (retain), `HEAP_SIZE_LIMIT: 4096`,
  PUID/PGID 1000, `DOMAIN` env for its web URL.
- **Why it doesn't deploy**: the HelmRelease sets
  `DOMAIN: "https://vaultwarden.${SECRET_CLUSTER_DOMAIN}"` —
  **`${SECRET_CLUSTER_DOMAIN}` is defined in no substitution source**
  (`cluster-settings`, `cluster-secrets`, `cluster-settings-user`,
  `cluster-secrets-user` all lack it) → the `cluster-apps-vaultwarden`
  Kustomization build fails and the app never reaches the cluster.
- **Fix (pick one)**:
  1. change the env to `${SECRET_DOMAIN}` (= `jesseisageek.com`), or
  2. add `SECRET_CLUSTER_DOMAIN: <your domain>` to
     `kubernetes/flux/vars/cluster-secrets.sops.yaml` (re-encrypt) and push.
  Then `flux reconcile -n flux-system kustomization cluster-apps-vaultwarden`.
- No `secret.sops.yaml` of its own (the vault's master-key model needs none);
  SMTP is commented out (`SMTP_FROM: vaultwarden@${SECRET_DOMAIN}`).
