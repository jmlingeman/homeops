# 08 — Versions & staleness audit

Every pinned version in this repo vs. current upstream. **Snapshot taken
2026-08-26** (ask for a fresh sweep to re-run).

Legend: 🟢 current · 🟡 mildly behind · 🔴 significantly behind / major jump
· ⚪️ no newer version in that repo (or upstream frozen)

Renovate (Saturdays) auto-updates everything in `kubernetes/` — a "stale" row
usually just means Renovate hasn't landed it yet (or Renovate can't bump it —
see gotchas at the end).

## 1. Infrastructure (manual upgrades — not Flux HelmReleases)

| Component | Pinned (where) | Current | | Notes |
|-----------|----------------|---------|---|-------|
| k3s | v1.29.0+k3s1 (`k3s_release_version`, `ansible/inventory/group_vars/kubernetes/main.yaml`) | v1.36.3+k3s1 | 🔴 | ~7 k8s minors behind. **The gate for everything else** (Longhorn's k8s compatibility, chart min-version requirements). Upgrade = its own project. |
| Flux | v2.2.2 (`kubernetes/flux/config/flux.yaml` OCI tag; `kubernetes/bootstrap/kustomization.yaml` ref) | v2.8.3 | 🟡 | Flux is self-upgrading from the OCI `flux-manifests` repo — a tag bump in `flux.yaml` upgrades the whole operator suite. |
| Cilium | chart 1.14.5 (`apps/kube-system/cilium/…` **and** `ansible/playbooks/templates/custom-cilium-helmchart.yaml.j2`) | 1.20.1 | 🔴 | Both copies must move together. |
| CoreDNS | chart 1.29.0 (same dual location, `custom-coredns-helmchart.yaml.j2`) | 1.47.0 (CoreDNS 1.14.6) | 🟡 | |
| metrics-server | 3.11.0 (`apps/kube-system/metrics-server/…`) | 3.14.0 | 🟡 | |
| descheduler | 0.29.0 (`apps/tools/descheduler/…`) | 0.36.0 | 🟡 | |
| Reloader | 1.0.62 (`apps/tools/reloader/…`) | 2.2.16 (app v1.4.21) | 🔴 | Chart is on a new 2.x series — major bump needs a values review. |
| Longhorn | 1.5.3 (`apps/storage/longhorn/…`) | 1.12.1 | 🔴 | 7 minors behind; upgrade is k8s-version gated — do it *after* the k3s bump and check the compatibility matrix. |
| openeBS localpv | 3.10.0 (`apps/storage/openebs/…`) | 3.10.0 (latest in repo) | ⚪️ | The repo hasn't published past 3.10.0, but the project moved to `dynamic-localpv-provisioner` (v4.6.0) — chart lags the app by two majors. |

## 2. Applications (Flux HelmReleases — `kubernetes/apps/**`)

"Chart" = `spec.chart.spec.version`; "Image" = the container image(s) the
release runs. Pinned values below are exactly as written in the repo.

### Network / infra services

| App | Chart pinned | Chart latest | Image pinned | Image current | |
|-----|-------------|-------------|--------------|---------------|---|
| cert-manager | v1.16.4 | v1.21.1 | chart default | v1.21.1 | 🔴 |
| ingress-nginx **internal + external** | 4.7.1 | 4.15.1 (controller v1.15.1) | chart default | — | 🔴 |
| external-dns | 1.14.1 | 1.21.1 (app v0.21.0) | chart default | — | 🔴 |
| k8s-gateway | 2.1.0 | 2.4.0 (2024-03, ~2.5 yrs old) | chart default | — | ⚪️ effectively unmaintained |
| cloudflared (app-template) | app-template 2.4.0 | 5.1.0 | `docker.io/cloudflare/cloudflared:2024.1.2` | 2026.8.2 | 🔴 image is ~2.5 yrs old — the tunnel binary |
| echo-server (app-template) | app-template 2.4.0 | 5.1.0 | `docker.io/jmalloc/echo-server:0.3.6` | v0.3.7 | 🟡 (upstream quiet ~2 yrs; low urgency) |

### Observability

| App | Chart pinned | Chart latest | Image pinned | Image current | |
|-----|-------------|-------------|--------------|---------------|---|
| grafana | 7.0.19 | 10.5.15 (Grafana 12.3.1) | chart default | Grafana 12.3.1 | 🔴 big jump (7.x → 10.x) |
| headlamp | 0.45.0 | 0.45.0 (newest, 2026-08-20) | chart default (`v<appVersion>` → `ghcr.io/headlamp-k8s/headlamp:v0.45.0`) | 0.45.0 | ✅ pinned at release; added as the kubernetes-dashboard replacement |
| kube-prometheus-stack | 55.8.1 | 88.5.4 (app v0.93.1) | chart default | — | 🔴 ~33 chart majors — **expect breaking changes** |
| kubernetes-dashboard | 6.0.8 | 7.14.0 | chart default | dashboard 2.0 | 🔴 **upstream retired** (moved to `kubernetes-retired/dashboard`); the HelmRepository URL `kubernetes.github.io/dashboard/` now 404s — the repo URL must move before any bump works |

### Database / security / default

| App | Chart pinned | Chart latest | Image pinned | Image current | |
|-----|-------------|-------------|--------------|---------------|---|
| postgresql (bitnami) | 13.2.29 | 18.8.13 (PG 18.6) | `bitnami/postgresql:15.4.0-debian-11-r39` | last 15.x = 15.4.0-debian-11-r45 | 🔴 **the pinned image tag now 404s on Docker Hub** (Bitnami purged versioned tags; only `latest` + digests remain) — a re-pull would fail. Pin a `latest@sha256:` digest or an available tag. |
| vaultwarden (app-template) ⚠️ not deployed | app-template 2.4.0 | 5.1.0 | `docker.io/vaultwarden/server:latest` (floating) | — | floating tag |
| homepage (app-template) | app-template 2.4.0 | 5.1.0 | `ghcr.io/gethomepage/homepage:v0.8.4` | v2.1.2 | 🔴 v0.8 → v2 — check config format compatibility before upgrading |

### Media

| App | Chart pinned | Image(s) pinned | Current image(s) | |
|-----|-------------|-----------------|------------------|---|
| sonarr | app-template 2.4.0 (+exportarr sidecar) | `lscr.io/linuxserver/sonarr:latest`, exportarr `ghcr.io/onedr0p/exportarr:v1.6.0` | Sonarr 4.0.19 (floating); exportarr v2.3.0 | 🟢 floating (current) / 🔴 exportarr sidecar stale |
| radarr | app-template 2.4.0 (+exportarr sidecar) | `lscr.io/linuxserver/radarr:latest`, exportarr `ghcr.io/onedr0p/exportarr:v1.6.0` | Radarr 6.3.0 (floating); exportarr v2.3.0 | 🟢 floating / 🔴 exportarr |
| lidarr | app-template 2.4.0 | `lscr.io/linuxserver/lidarr:latest` | Lidarr 3.1.0 (floating) | 🟢 |
| prowlarr | app-template 2.4.0 | `lscr.io/linuxserver/prowlarr:latest` | Prowlarr 2.5.2 (floating) | 🟢 |
| sabnzbd | app-template 2.4.0 | `lscr.io/linuxserver/sabnzbd:latest` | SABnzbd 5.1.2 (floating) | 🟢 |
| overseerr | app-template 2.4.0 | `sctx/overseerr:latest` (community fork) | fork's 1.35.0, Feb 2026 (~6 months stale) | 🟡 |
| youtarr | app-template 2.4.0 (+mariadb 10.3 sidecar) | `dialmaster/youtarr:latest` | v1.80.0 (Aug 2026; repo renamed to DialmasterOrg/Youtarr) | 🟢 floating |
| ultrasonics ⚠️ not deployed | app-template 2.4.0 | `docker.io/xdgfx/ultrasonics-api:latest` | no releases; dormant upstream (last push 2025-05) | ⚪️ |
| piped | **piped 8.1.23** (own chart) | `logicalkarma/piped-proxy:latest` + `smidget2k4/piped-backed:latest@sha256:7289…` | proxy floating; backend community fork (digest-pinned, Docker Hub updated 2026-05) | 🔴 chart 8.1.29 available (6 behind); images floating |
| jellyfin | (external VM 192.168.1.211 — no in-repo image) | — | 10.11.11 | reference only |

### Home

| App | Chart pinned | Image pinned | Current | |
|-----|-------------|--------------|---------|---|
| gitea | 10.6.0 (dl.gitea.io; bundles Gitea 1.22.3) | chart default | chart 12.7.0 (Gitea 1.27.0) | 🔴 |
| grocy | 8.5.2 (k8s-at-home; **org archived, chart frozen**) | chart default (grocy 3.x) | chart frozen; app is at v4.6.0 | ⚪️ chart / 🟡 app |
| homarr | 5.7.0 (homarr-labs; bundles v1.32.0) | chart default | 8.28.0 (v1.76.0) | 🔴 |
| actual | app-template 2.4.0 | `docker.io/actualbudget/actual-server:24.2.0-alpine` | 26.8.1-alpine | 🔴 ~2 yrs behind |
| firefly-iii | app-template 2.4.0 | `docker.io/fireflyiii/core:latest` (floating) | v6.6.6 (via latest) | floating |
| firefly-iii-importer | app-template 2.4.0 | `docker.io/fireflyiii/data-importer:latest` (floating) | — | floating |
| joplin | app-template 2.4.0 | `docker.io/joplin/server:latest` (floating) | 3.7.1 (via latest) | floating |
| mealie | app-template 2.4.0 | `docker.io/hkotel/mealie:v1.10.2` | v3.24.0 (the fork now publishes upstream v3.x tags) | 🔴 |
| transiter ⚠️ orphaned | app-template 2.4.0 | `docker.io/jamespfennell/transiter:latest` (floating) | v1.0.0 (via latest) | floating |

### Frontend (the "puus" suite)

All eight use **app-template 2.4.0** (current 5.1.0 🔴) and **floating
`latest` tags** (only libremdb pins one):

| App | Image pinned | Current upstream | |
|-----|--------------|------------------|---|
| breezewiki | `quay.io/pussthecatorg/breezewiki:latest` | no version tags; quay rebuild from HEAD ~every 3h, active | floating |
| librarian | `quay.io/pussthecatorg/librarian:latest` | **upstream archived** (last release v0.10.3, 2022) | floating — candidate for removal |
| libreddit (Redlib) | `docker.io/tagliasteel/redlib` (no tag → latest) | fork 0.36.0 (May 2026); upstream redlib-org v0.36.0 | floating |
| libremdb | `ghcr.io/zyachel/libremdb:v4.5.0` | v4.5.0 | 🟢 |
| priviblur | `quay.io/pussthecatorg/priviblur:latest` | v0.3.0 (Mar 2025); post-release dev only | floating |
| quetre | `quay.io/pussthecatorg/quetre:latest` | v8.0.0 (2024); unreleased dev after | floating |
| rimgo | `quay.io/pussthecatorg/rimgo:latest` | v1.4.2 (2026-04); v2.0-rc in progress | floating |
| scribe | `quay.io/pussthecatorg/scribe:latest` | **private image** — no public upstream; version unknown | floating (opaque) |

**Floating-tag caveat**: `latest` means the *running image moves under you*
whenever the publisher rebuilds (the pussthecatorg quay images rebuild ~every
3 hours) — you never deploy an old version, but you also have no rollback
point and no changelog. If reproducibility matters, pin explicit tags (libremdb
is the model) or digests.

## 3. Notable findings (act on these)

1. **`bitnami/postgresql:15.4.0-debian-11-r39` is gone from Docker Hub** (Bitnami
   purged the versioned tags). The in-cluster pod is running a cached copy, but
   any re-pull (new node, reschedule) would **fail**. Pin
   `latest@sha256:<digest of the running image>` or an available tag.
2. **kubernetes-dashboard is upstream-retired**; its HelmRepository URL
   (`kubernetes.github.io/dashboard`) 404s. **Headlamp (0.45.0) has been added**
   as its replacement (observed the official kubernetes.io migration path) —
   once it proves itself, retire the kubernetes-dashboard addon.
   homepage, vaultwarden). Bump it once, smoke-test the suite.
4. **kube-prometheus-stack 55 → 88** (~33 majors) — do this as its own
   maintenance window; expect value/API changes.
5. **cloudflared 2024.1.2** — the tunneling binary is 2.5 years old; it works,
   but Cloudflare occasionally deprecates old clients (QUIC/tunnel API).
6. **k3s 1.29** gates the rest (Longhorn, some chart min-k8s). Plan it as a
   project: bump `k3s_release_version`, `task k3s` (master `--server`, worker
   `--agent`), then re-run this audit.

## 4. What Renovate can and can't do here

- **Covers** (fileMatch `kubernetes/`, `addons/`, `ansible/`): all HelmRelease
  chart versions + image tags in `kubernetes/apps/**` (including the `latest`
  *images*? **no** — Renovate skips floating tags; it only manages pinned
  versions/digests). So pinned rows get PRs; `latest` rows don't move at all
  from Renovate (they move via the publisher's rebuilds, see the caveat above).
- **Does not cover** `bootstrap/templates/**` — templates pin app-template
  2.4.0, cloudflared 2024.1.2, nginx 4.7.1, etc., and `task configure` will
  overwrite any hand-fixed `kubernetes/` copy from them. Extend Renovate's
  `flux` manager fileMatch with the regex in
  [93-sop-image-to-app.md](93-sop-image-to-app.md#23-keeping-the-image-up-to-date)
  (or accept manual template bumps).
