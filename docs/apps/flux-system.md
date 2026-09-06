# flux-system

Flux itself is installed by `task flux:bootstrap` from
`kubernetes/bootstrap/` (not reconciled by Flux). The only *app* in this
namespace is the webhook receiver, under `addons/`.

## flux-webhooks (GitHub)

`addons/webhooks/github/` — makes pushes reconcile instantly instead of
waiting for the 30m interval:

- **`receiver.yaml`** — Flux `Receiver` `github-receiver`:
  - `type: github`, `event: [ping, push]`
  - `address: ":9293"`, resources to reconcile: `home-kubernetes`
    (GitRepository), `cluster` + `cluster-apps` (Kustomizations)
  - `secretRef: github-webhook-token-secret`
- **`ingress.yaml`** — Ingress `flux-webhook` (class **external**, host
  `flux-webhook.${SECRET_DOMAIN}`, external-dns target) →
  `github-receiver:9293`. Public, but every request must match the token.
- **`secret.sops.yaml`** — `github-webhook-token-secret` with key `token`
  (value from `bootstrap/vars/config.yaml` → `bootstrap_flux_github_webhook_token`).

Configure the GitHub webhook (repo → Settings → Webhooks): POST to
`https://flux-webhook.jesseisageek.com/hook/<path>` (get the path via
`kubectl -n flux-system get receiver github-receiver -o jsonpath='{.status.webhookPath}'`),
secret = the same token. See [../91-runbook.md](../91-runbook.md).

## Other flux-system state (not app-managed)

- `sops-age` Secret (created by `task flux:bootstrap`) — the age private key
  used to decrypt every `*.sops.yaml`. **Never delete.**
- `cluster-secrets` / `cluster-secrets-user` Secrets (from
  `kubernetes/flux/vars/*.sops.yaml`) — the `${SECRET_*}` substitution
  sources.
- `flux-manifests` OCIRepository + `flux` Kustomization (self-upgrade,
  v2.2.2) — from `kubernetes/flux/config/flux.yaml`.
- HPA for the flux controllers (qps/burst 1000, OOM watchdog).
