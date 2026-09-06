# media

The *arr / media stack. All *arr apps: app-template, `lscr.io/linuxserver/*:latest`,
internal ingress, Longhorn config PVC, NFS data on 192.168.1.30
(`${NFS_SERVER}`-equivalent, mostly hardcoded).

## Flow

```
overseerr (requests) ──► sonarr / radarr / lidarr / youtarr ──► sabnzbd (usenet) + prowlarr (indexers)
jellyfin (external, 192.168.1.211) plays /tv /movies /music /downloads
piped (public YouTube front), ultrasonics (Plex scrobble), piped/ytproxy
```

## sonarr

TV series automation (port 8989). Config 16Gi longhorn; NFS: downloads
`/mnt/pool1/downloads`, tv `/mnt/pool1/tv`, tv2 `/mnt/pool2/tv`.
**exportarr sidecar** (Prometheus metrics, port 9794) + Grafana dashboard
(`configMapGenerator grafana-dashboards-sonarr`, folder `Media`, gnet 12530).
Hajimari icon `television-box`. **The reference app-template app in this repo** —
new *arr-style apps should copy it.

## radarr

Movie automation (port 7878). Config 1Gi longhorn; NFS downloads
`/mnt/pool1/downloads`, `tv` volume maps `/mnt/pool2/movies` → `/movies`.
exportarr sidecar + `grafana-dashboards-radarr` dashboard (gnet 12530-ish, folder
`Media`).

## lidarr

Music automation (port 8686). Config 8Gi longhorn; NFS downloads
`/mnt/pool1/downloads`, music `/mnt/pool2/music`.
`secret.sops.yaml` (`lidarr-secret`: `arlToken`, `plexToken`, `plexUrl`) exists but
is **commented out of the kustomization** — currently unused (Auralis/ARL + Plex
tokens for a future ultrasonics/ARL integration).

## prowlarr

Indexer management for the *arrs (port 9696). Config 1Gi longhorn. Hajimari
`television-box`.

## sabnzbd

Usenet downloader (port 8080, probe `/api?mode=version`). Config 1Gi longhorn, NFS
downloads `/mnt/pool1/downloads`. **Memory limit 12Gi** (usenet indexing is
hungry). No hajimari/dashboard.

## overseerr

Request portal (image `sctx/overseerr`, port 5055 — the `sctx` fork keeps the old
port; official overseerr uses 5055 too in v1 but this is the maintained community
fork). Config 16Gi longhorn. Hajimari `television-box`.

## jellyfin ⚠️

**Not running in-cluster** — a kustomize-only app (no HelmRelease) made of
`service.yaml` + **static `endpoint.yaml`** (points to `192.168.1.211:8096`, the
external Jellyfin VM) + `ingress.yaml`
(host `jellyfin.${SECRET_DOMAIN}`, `rewrite-target: /`).
⚠ `ingressClassName: nginx` — a class that doesn't exist here (only `internal` /
`external`) and a hardcoded `secretName: tls-dev-com` → the ingress never gets an
address. Dormant stub; fix the class + TLS secret if you want it live.

## piped

Self-hosted YouTube front (piped repo chart 8.1.23; image
`smidget2k4/piped-backed:latest@sha256:…`, ytproxy `logicalkarma/piped-proxy`).
**Public**: three external ingresses — `piped` (UI), `pipedapi` (API), `ytproxy`
(stream proxy), all with external-dns targets.
⚠ `piped-secret` (sops; `DB_PASSWORD`, `DB_USERNAME`, `hostname`, `password`,
`username`) is **commented out of the kustomization** although the HelmRelease
references it (db `piped` on the shared `postgresql` in the `database` ns) — the
Secret presumably exists in-cluster from a prior manual apply; re-enable the
kustomization line to make it GitOps-managed.

## youtarr

YouTube "TV" downloader (image `dialmaster/youtarr`, port 3011, `/api/health`):
downloads new episodes of configured shows. Two controllers in one HelmRelease:
`youtarr-db` (mariadb 10.3) + `main`. Own sops secret `youtarr-secrets`
(`POSTGRES_HOST/PASS/USER` — misnamed, it's actually MySQL). NFS: downloads
`/mnt/pool1/downloads`, temp `/mnt/pool2/temp` (mounted at path `/tv2` — name/path
mismatch quirk). Hajimari `television-box`.

## ultrasonics ⚠️ ORPHANED

Plex scrobbler (`xdgfx/ultrasonics-api`, port 8003, `/ready`): watches Plex
activity, forwards to Auralis etc. Config 8Gi longhorn; NFS downloads/music
(nfsvers 4.1). Its `secret.sops.yaml` is a copy-paste of lidarr's (named
`lidarr-secret`) and is commented out; the HelmRelease references no secret.
**`ultrasonics/ks.yaml` is not listed in `media/kustomization.yaml` → not
deployed.** To enable: add `- ./ultrasonics/ks.yaml` to
`kubernetes/apps/media/kustomization.yaml` (and sort out the misnamed secret if
you want the ARL/Plex env).
