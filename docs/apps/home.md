# home

Personal/family apps. Mostly internal; gitea + grocy are public.

## actual

[Actual Budget](https://actual.co) server (image `actualbudget/actual-server:24.2.0-alpine`,
port 5006). Data 4Gi longhorn at `/data`. Internal ingress `actual.${SECRET_DOMAIN}`.
(No sops secret — the API key is set in the app UI, not env.)

## firefly-iii (+ importer)

[Firefly III](https://firefly-iii.org) double-entry personal finance
(image `fireflyiii/core`, port 8080). Kustomization `cluster-apps-firefly-iii`
(dependsOn `postgresql`) + a second Kustomization for `importer/`.

- **Secrets**: `firefly-iii-secrets` (sops: `API_KEY`, `APP_KEY`, `POSTGRES_DB`,
  `POSTGRES_HOST`, `POSTGRES_PASS`, `POSTGRES_USER`) — used via `secretKeyRef` /
  `envFrom` (note: the sops file is **commented out of the kustomization**; the
  Secret must exist in-cluster from an earlier apply — same situation as `piped`).
- **Storage**: `existingClaim` `fireflyiii-config-v1` (1Gi longhorn, RWO) at
  `/var/www/html/firefly-iii/storage/upload`.
- **Ingress**: `firefly.${SECRET_DOMAIN}` internal. `TRUSTED_PROXIES: "**"` with a
  TODO comment (bypasses the internal ingress' real-IP check — fine behind the
  internal nginx, tighten if you expose it).
- **`importer/`**: `firefly-iii-importer` (regular controller) +
  `firefly-iii-importer-cba` (**cronjob** controller, `0 17 * * *`,
  `ttlSecondsAfterFinished: 86400`), both `fireflyiii/data-importer`, both with
  an internal ingress on `firefly-importer.${SECRET_DOMAIN}` — nightly import of
  transactions.

## gitea

[Self-hosted Git](https://gitea.io) (official chart 10.6.0, dl.gitea.io) with its
bundled PostgreSQL subchart. **Public**: `gitea.${SECRET_DOMAIN}` external +
external-dns target. Chart-default persistence (no size/storageClass override).
No sops secret in the dir (admin user configured in-app / first boot).

## grocy

[grocy](https://grocy.info) garden management (k8s-at-home chart 8.5.2).
**Public**: `grocy.${SECRET_DOMAIN}` external + external-dns target. Config 1Gi
longhorn.

## homarr

[Homarr](https://homarr.lol) dashboard (homarr-labs chart 5.7.0, bundled
PostgreSQL). Internal `homarr.${SECRET_DOMAIN}`.
⚠ carries a `internal-dns.alpha.kubernetes.io/target` annotation — a **nonstandard
prefix** (the real one is `external-dns.alpha.kubernetes.io/…`); it's a no-op
typo.

## joplin

[Joplin](https://joplin.app) **sync server** (image `joplin/server`, port 22300)
— the backend for the Joplin desktop/mobile apps. Data 4Gi longhorn at
`/app/data`. Internal ingress. (No sops secret — the Joplin app connects with
the URL only; no auth configured in the manifests.)

## mealie

[Mealie](https://mealie.io) recipe manager (image `hkotel/mealie:v1.10.2`, port
9000). Data 4Gi longhorn. Internal ingress. (Probe block commented out; no sops
secret.)

## transiter ⚠️ ORPHANED

`transiter/ks.yaml` is a **verbatim copy of `media/overseerr/ks.yaml`** (Kustomization
named `cluster-apps-overseerr`, path `./kubernetes/apps/media/overseerr/app`) and
the dir is **not listed in `home/kustomization.yaml`** → never applied. The
HelmRelease inside declares `namespace: media` too. If you want this app
(`jamespfennell/transiter`), rewrite the ks to point at its own `app/` dir, name
it `cluster-apps-transiter`, set `namespace: home`, and register it in
`home/kustomization.yaml`.
