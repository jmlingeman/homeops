# App Catalog

One file per namespace. Each app entry: what it is, how it's deployed, ingress, storage,
secrets, and anything unusual. Deployment status:

- ✅ **deployed** — Kustomization registered in the namespace `kustomization.yaml`.
- ⚠️ **orphaned / broken** — manifests exist but Flux won't (or can't) deploy them.

## Overview

| Namespace | Apps (✅ deployed unless noted) |
|-----------|----------------------------------|
| [flux-system](flux-system.md) | flux-webhooks (GitHub webhook receiver) |
| [kube-system](kube-system.md) | cilium, coredns, metrics-server |
| [network](network.md) | nginx (internal+external), k8s-gateway, external-dns, cloudflared, echo-server |
| [cert-manager](cert-manager.md) | cert-manager (+ ClusterIssuers) |
| [storage](storage.md) | longhorn, openebs |
| [database](database.md) | postgresql |
| [media](media.md) | jellyfin (external proxy), lidarr, overseerr, prowlarr, radarr, sabnzbd, sonarr, piped, youtarr; ⚠️ ultrasonics (orphaned) |
| [home](home.md) | actual, firefly-iii (+importer), gitea, grocy, homarr, joplin, mealie; ⚠️ transiter (orphaned) |
| [frontend](frontend.md) | breezewiki, librarian, libreddit, libremdb, priviblur, quetre, rimgo, scribe |
| [default](default.md) | homepage |
| [observability](observability.md) | grafana, headlamp, kube-prometheus-stack, kubernetes-dashboard |
| [security](security.md) | ⚠️ vaultwarden (registered but build broken) |
| [tools](tools.md) | descheduler, reloader |
| tools | flux-diff, ncp-sshfs, nerkho |
| wireguard / wg-easy | optional VPN addons (both disabled by default — see [vpn.md](vpn.md)) |

### Deployment-status notes (⚠️)

- **`media/ultrasonics`** — `ultrasonics/ks.yaml` exists (Kustomization
  `cluster-apps-ultrasonics`) but is **not listed** in `kubernetes/apps/media/kustomization.yaml`
  → never applied. To deploy: add `- ./ultrasonics/ks.yaml` to that file.
- **`home/transiter`** — `transiter/ks.yaml` is a **verbatim copy of `media/overseerr/ks.yaml`**
  (named `cluster-apps-overseerr`, path `./kubernetes/apps/media/overseerr/app`) and is **not
  listed** in `kubernetes/apps/home/kustomization.yaml` → orphaned; if you fix the ks, the
  HelmRelease itself declares `namespace: media`.
- **`security/vaultwarden`** — registered in `security/kustomization.yaml`, but its
  HelmRelease references the variable `${SECRET_CLUSTER_DOMAIN}`, which is **not defined in
  any of the four substitution sources** (`cluster-settings*` / `cluster-secrets*`) → the
  Kustomization build fails and the app never deploys. Fix: add `SECRET_CLUSTER_DOMAIN` to
  `kubernetes/flux/vars/cluster-secrets.sops.yaml` (or change the env to `${SECRET_DOMAIN}`).
- **`media/jellyfin`** — deployed, but its ingress uses `ingressClassName: nginx` (a class
  that doesn't exist here — only `internal` and `external` are defined) and a hardcoded TLS
  secret `tls-dev-com` → the ingress has no address; treat it as a dormant external-proxy
  stub for the Jellyfin at `192.168.1.211:8096`.

## Conventions used by every app

- `ks.yaml` → Flux `Kustomization`, name `cluster-apps-<app>`, `prune: true`,
  `wait: true`, `interval: 30m`, `retryInterval: 1m`, `timeout: 5m`,
  `sourceRef: GitRepository/home-kubernetes` (some older ones are named differently —
  see per-app notes).
- `app/` → usually `helmrelease.yaml` + `kustomization.yaml` (+ `secret.sops.yaml`,
  `configmap.yaml`, `pvc.yaml`, `grafana-dashboards/*.json` as needed).
- Ingress hosts: `<app>.${SECRET_DOMAIN}` (= `*.jesseisageek.com`); class `internal`
  (default) or `external` (public, + `external-dns.alpha.kubernetes.io/target:
  external.${SECRET_DOMAIN}`).
- Config persistence: Longhorn PVCs (`storageClass: longhorn`, `retain: true`);
  media data: NFS on `192.168.1.30` (custom volumeSpec).
- `reloader.stakater.com/auto: "true"` on nearly every app-template controller.
- Namespace files carry `kustomize.toolkit.fluxcd.io/prune: disabled` and a leftover
  `kyverno.io/add-ndots: "true"` label (no Kyverno deployed — inert).
