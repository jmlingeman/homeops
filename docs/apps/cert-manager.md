# cert-manager

One app dir, two Kustomizations (in `ks.yaml`):

## cert-manager

chart `cert-manager` v1.16.4 (jetstack repo). Prometheus enabled
(serviceMonitor, `prometheusInstance: observability`).
`app/prometheusrule.yaml` — 4 alerts from the cert-manager-mixin:
`CertManagerAbsent`, `CertManagerCertExpirySoon` (<21 days),
`CertManagerCertNotReady`, `CertManagerHittingRateLimits` (429s).

## cert-manager-issuers (dependsOn `cert-manager`)

- `issuers/issuers.yaml` — two **ClusterIssuers**, both ACME **DNS-01 via Cloudflare**
  (token key `api-token` from `cert-manager-secret`, sops-encrypted), solver restricted
  to zone `${SECRET_DOMAIN}`, email `${SECRET_ACME_EMAIL}`:
  - `letsencrypt-production` (ACME v02 production)
  - `letsencrypt-staging` (ACME staging)
- `issuers/secret.sops.yaml` → `cert-manager-secret` (`api-token`).

The actual `Certificate` objects live in `apps/network/nginx/certificates/`
(production: `jesseisageek.com` + `*.jesseisageek.com` → secret
`jesseisageek-com-production-tls`, used as both nginx controllers' default cert).
