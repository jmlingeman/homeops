# 90 — SOP: Add a New App

All three methods below land in the same place: `kubernetes/apps/<ns>/<app>/` with a `ks.yaml`
(Flux Kustomization) + an `app/` dir, referenced from the namespace `kustomization.yaml`.
Flux picks it up on the next reconcile (≤30m, or push with the webhook, or
`task flux:reconcile`).

> **Which SOP?** This one edits `kubernetes/` **directly** — fine for quick experiments,
> but in this repo every app has a template, so the result is **overwritten on the next
> `task configure`** (e.g. `./deploy.sh`). For any app you mean to keep, use
> **[92-sop-add-app-from-template.md](92-sop-add-app-from-template.md)** instead — it's the
> same flow applied to the `bootstrap/templates/` layer.

> ⚠ `bin/add_app.py` **is not a working tool** — it prompts for input and builds a template
> string but never writes any files (and its `{{name}}` placeholders don't interpolate).
> Do not use it.

## App directory layout

```
kubernetes/apps/<ns>/
├── namespace.yaml                     # already exists per namespace
├── kustomization.yaml                 # ← STEP 4: add ./<app>/ks.yaml to resources
└── <app>/
    ├── ks.yaml                        # ← STEP 2 (one Flux Kustomization per app)
    └── app/
        ├── kustomization.yaml         # ← STEP 3: lists the files below
        ├── helmrelease.yaml           # ← STEP 3 (methods A1 / B)
        └── secret.sops.yaml           # ← STEP 5 (only if the app has secrets)
```

## Common steps (all methods)

1. **Pick the namespace.** Existing: `media`, `home`, `frontend`, `default`, `tools`, …
   For a *new* namespace: copy an existing `<ns>/namespace.yaml` + `kustomization.yaml`
   (namespace files carry `kustomize.toolkit.fluxcd.io/prune: disabled`, so deleting the
   Kustomization later doesn't delete the namespace).
2. **Create `kubernetes/apps/<ns>/<app>/ks.yaml`** (shown in each method below).
3. **Create `app/`**: `kustomization.yaml` + the resource files.
4. **Register it**: add `- ./<app>/ks.yaml` to `kubernetes/apps/<ns>/kustomization.yaml`.
5. **Secrets** (if any): write `app/secret.sops.yaml` as a plain `v1 Secret` with
   `stringData`, list it in `app/kustomization.yaml`, then
   `task sops:encrypt file=kubernetes/apps/<ns>/<app>/app/secret.sops.yaml`.
   Reference the keys from the HelmRelease via `secretKeyRef`/`envFrom`.
   Full workflow: [04-secrets-sops.md](04-secrets-sops.md).
6. **Validate locally** before pushing:
   ```sh
   ./scripts/kubeconform.sh kubernetes        # strict schema check of every kustomization
   # or, for a faster single-namespace check (needs flux-local):
   flux-local build kustomization --path kubernetes/apps/<ns>
   ```
7. **Commit + push.** The **flux-diff** GitHub workflow
   (`.github/workflows/flux-diff.yaml`) posts the in-cluster diff of the changed
   kustomizations/HelmReleases as a PR comment — read it to confirm exactly what changes.
8. **Verify**:
   ```sh
   flux get ks -A | grep cluster-apps-<app>        # READY=True, SUSPENDED=False, no Reconciling errors
   flux get hr -n <ns> <app>                       # (HelmRelease-based apps)
   kubectl -n <ns> get pods -o wide                # Running
   kubectl -n <ns> get ingress                     # host/class as expected
   ```
   To force an immediate reconcile after push: `task flux:reconcile`.

---

## Method A — From a Docker image

Two variants. **A1 (bjw-s `app-template`) is the house pattern** — most apps in this cluster
use it (sonarr, radarr, overseerr, ultrasonics, joplin, actual, …). A2 (raw kustomize) is for
apps you want to control manifest-by-manifest (the only current user is `jellyfin`, which
is actually an external proxy — see [05-apps/media.md](apps/media.md)).

### A1. app-template HelmRelease (recommended)

`app-template` (bjw-s, OCI repo `oci://ghcr.io/bjw-s/helm`, already registered) is a generic
chart that turns one container image into a Deployment + Service + Ingress + persistence,
driven purely by YAML values.

`kubernetes/apps/<ns>/<app>/ks.yaml`:

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cluster-apps-<app>
  namespace: flux-system
spec:
  path: ./kubernetes/apps/<ns>/<app>/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: true
  interval: 30m
  retryInterval: 1m
  timeout: 5m
```

`kubernetes/apps/<ns>/<app>/app/kustomization.yaml`:

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./helmrelease.yaml
  # - ./secret.sops.yaml        # uncomment if the app has secrets
```

`kubernetes/apps/<ns>/<app>/app/helmrelease.yaml` — modeled on the real `media/sonarr`:

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: &app <app>
  namespace: <ns>
spec:
  interval: 15m
  chart:
    spec:
      # renovate: registryUrl=https://bjw-s.github.io/helm-charts/
      chart: app-template
      version: 2.4.0
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  maxHistory: 2
  install:
    createNamespace: true
    remediation: { retries: 3 }
  upgrade:
    cleanupOnFail: true
    remediation: { retries: 3 }
  uninstall:
    keepHistory: false
  values:
    controllers:
      main:
        annotations:
          reloader.stakater.com/auto: "true"     # auto-restart on ConfigMap/Secret change
        containers:
          main:
            image:
              repository: docker.io/OWNER/IMAGE
              tag: latest                          # renovate manages the tag
            env:
              PORT: &port 8080
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet: { path: /, port: *port }
                  initialDelaySeconds: 0
                  periodSeconds: 10
                  timeoutSeconds: 1
                  failureThreshold: 3
              readiness: *probes
              startup: { enabled: false }
    env:
      TZ: ${TIMEZONE}
      PUID: 1000
      PGID: 1000
    service:
      main:
        ports:
          http: { port: *port }
    ingress:
      main:
        enabled: true
        className: internal              # or: external (public via Cloudflare, see below)
        hosts:
          - host: &host "<app>.${SECRET_DOMAIN}"
            paths:
              - path: /
                pathType: Prefix
                service: { name: main, port: http }
        tls:
          - hosts: [*host]
    podSecurityContext:
      supplementalGroups: [1000]
    persistence:
      config:
        enabled: true
        mountPath: /config
        storageClass: longhorn
        size: 8Gi
        retain: true
    resources:
      requests: { cpu: 15m, memory: 256Mi }
      limits:   { memory: 512Mi }
```

Notes:

- **Ingress class**: `internal` (default, LAN + split-DNS) or `external`. For `external`
  also add `annotations: { "external-dns.alpha.kubernetes.io/target": "external.${SECRET_DOMAIN}" }`
  under `ingress.main` so external-dns publishes it through the Cloudflare-proxied name
  (see `gitea`/`grocy` for real examples).
- **Secrets**: reference keys like
  ```yaml
  env:
    MY_PASSWORD:
      valueFrom:
        secretKeyRef: { name: <app>-secret, key: MY_PASSWORD }
  ```
- **NFS volumes** (media apps) use `persistence.<name>.type: custom` +
  `volumeSpec: { nfs: { server: "${NFS_SERVER}", path: "${NFS_TV}" } }` — note existing
  manifests mostly hardcode `192.168.1.30` and the raw `/mnt/pool…` paths.
- **Metrics**: add a `sidecars.exporter` block (see sonarr's exportarr sidecar) and a
  `serviceMonitor` if the app exposes `/metrics`.
- **Hajimari/homepage icons**: `annotations: { "hajimari.io/enable": "true", "hajimari.io/icon": "icon-name" }`
  on the ingress (used by several apps; homepage auto-discovers ingresses).
- **YAML anchors** (`&port`, `*host`, `*probes`) are the repo convention for keeping
  ports/hosts in sync — follow it.

### A2. Raw kustomize (no Helm)

Use when the app has no decent chart and you want plain manifests. Example in the wild here:
`media/jellyfin` — `app/` contains `service.yaml` + `endpoint.yaml` + `ingress.yaml` and a
`kustomization.yaml` listing them (no `helmrelease.yaml`). For a normal in-cluster
container you'd write `deployment.yaml` + `service.yaml` + `ingress.yaml` instead.

`ks.yaml` is identical to A1 (the Kustomization doesn't care what's in `app/`).
Caveats: no Helm remediation/retries (reconciliation is best-effort), no `helm.sh/chart`
metadata, updates are manual image bumps.

---

## Method B — From a Helm chart

For apps with a real chart: gitea (official), grocy (k8s-at-home), homarr (homarr-labs),
piped (own repo), postgresql (bitnami), longhorn, …

1. **Check the chart repo is registered** in `kubernetes/flux/repositories/helm/`.
   If not, add `<repo>.yaml`:
   ```yaml
   ---
   apiVersion: source.toolkit.fluxcd.io/v1beta2
   kind: HelmRepository
   metadata:
     name: <repo>
     namespace: flux-system
   spec:
     interval: 1h
     url: https://CHART_REPO_URL
   ```
   …and list it in `kubernetes/flux/repositories/helm/kustomization.yaml`.
   OCI-based repos use `type: oci` + `url: oci://…` (see `bitnami.yaml`, `bjw-s.yaml`,
   `prometheus-community.yaml`).
   ⚠ `kubernetes/flux/repositories/` is part of the **`cluster`** Kustomization
   (path `./kubernetes/flux`) — it applies before apps, no per-app ks needed.
2. **`app/helmrelease.yaml`** — same shape as Method A1 but a real chart, e.g. modeled on
   `home/gitea`:
   ```yaml
   ---
   apiVersion: helm.toolkit.fluxcd.io/v2beta2
   kind: HelmRelease
   metadata:
     name: <app>
     namespace: <ns>
   spec:
     interval: 30m
     chart:
       spec:
         chart: <chart-name>
         version: X.Y.Z            # renovate: registryUrl=…  (comment triggers renovate)
         sourceRef:
           kind: HelmRepository
           name: <repo>
           namespace: flux-system
     maxHistory: 2
     install:
       createNamespace: true
       remediation: { retries: 3 }
     upgrade:
       cleanupOnFail: true
       remediation: { retries: 3 }
     uninstall:
       keepHistory: false
     values:                     # chart-specific values (ingress, persistence, env, secrets…)
       …
   ```
   Chart-specific `values:` — keep small; consult the chart README. For bitnami charts
   the `postgresql` app is the local example (values: auth, persistence, service, ingress).
3. **`ks.yaml`** — identical to Method A1.
4. Steps 4–8 of the common flow.

**Choosing a repo**: prefer the official/author chart (gitea, prometheus-community,
longhorn, jetstack) over k8s-at-home wrappers; k8s-at-home is fine for personal apps
(grocy). If a chart exists in both an HTTP repo and OCI, this repo already standardizes
on OCI for bjw-s/prometheus-community/bitnami.

---

## Method C — From a Git repository

Two sub-cases. **No app currently uses a separate git source** in this cluster
(`kubernetes/flux/repositories/git/` and `oci/` kustomizations are empty) — everything is
in this repo — so treat this as the pattern to introduce when an app's manifests live
elsewhere (a personal kustomize repo, a project that only ships kustomize manifests, …).

### C1. Plain kustomize manifests in a repo

1. Register the source in `kubernetes/flux/repositories/git/`:
   ```yaml
   ---
   apiVersion: source.toolkit.fluxcd.io/v1
   kind: GitRepository
   metadata:
     name: <app>-repo
     namespace: flux-system
   spec:
     interval: 30m
     url: https://github.com/<user>/<repo>.git
     ref:
       branch: main
     # if the repo is private: secretRef: { name: github-deploy-key }
     #   + kubernetes/bootstrap/github-deploy-key.sops.yaml (README "Authenticate Flux over SSH")
   ```
   and list it in `kubernetes/flux/repositories/git/kustomization.yaml`.
2. Create `kubernetes/apps/<ns>/<app>/ks.yaml` pointing at the repo instead of the
   local path:
   ```yaml
   ---
   apiVersion: kustomize.toolkit.fluxcd.io/v1
   kind: Kustomization
   metadata:
     name: cluster-apps-<app>
     namespace: flux-system
   spec:
     targetNamespace: <ns>
     path: ./deploy/kustomize        # path inside the external repo
     prune: true
     sourceRef:
       kind: GitRepository
       name: <app>-repo
     wait: true
     interval: 30m
     retryInterval: 1m
     timeout: 5m
     # sops decryption + ${var} substitution are NOT auto-added for non-local sources:
     # add these blocks if the external manifests need them:
     # decryption: { provider: sops, secretRef: { name: sops-age } }
     # postBuild:
     #   substituteFrom:
     #     - { kind: ConfigMap, name: cluster-settings }
     #     - { kind: Secret,    name: cluster-secrets }
   ```
3. `targetNamespace` is required here (the manifests aren't in a namespace dir of this
   repo; the namespace itself still needs to exist — create one in
   `kubernetes/apps/<ns>/namespace.yaml` if the ns doesn't exist yet).
4. No `app/` dir needed — the Kustomization builds the external repo's kustomization.
5. Common steps 6–8 (validate with kubeconform only for the in-repo parts; the external
   kustomization is validated in-cluster — check `flux get ks` and the PR's flux-diff).

### C2. Helm chart stored in a git repo

Same as Method B, but the HelmRelease's chart source is a GitRepository:

```yaml
spec:
  chart:
    spec:
      chart: ./charts/<chart>        # path to the chart dir inside the repo
      sourceRef:
        kind: GitRepository
        name: <app>-repo
```

This is how k8s-at-home charts *could* be consumed (their docs recommend the HTTP repo
instead). Use it when you want to pin the chart to a repo tag/branch rather than a
published chart version.

### C3. (Alternative) OCI images via Piraeus

The `piraeus` and `movetokube` HelmRepositories are registered but **unused**. Piraeus
can deploy a plain Docker image through a HelmChart without an app-template wrapper
(`Piraeus`/`Pod`-style CRs). If you ever want "docker image → chart" with less YAML than
app-template, wire those up — otherwise stick with Method A1.

---

## Removing an app

1. Delete `kubernetes/apps/<ns>/<app>/`.
2. Remove `- ./<app>/ks.yaml` from `kubernetes/apps/<ns>/kustomization.yaml`.
3. Push. `prune: true` on the Kustomization removes everything Flux created (deployments,
   ingresses, services) — **but not PVCs** (check for `retain: true`/default retain; Longhorn
   PVCs survive deletion and keep their data; delete explicitly if you want them gone) and
   not `Namespace`s (protected by the `prune: disabled` label).
4. Verify: `flux get ks -A` (the old ks is gone), `kubectl -n <ns> get all`.
