# 92 — SOP: Add a New App (the Persistent Way — via Templates)

In this repo **every app under `kubernetes/` is generated from `bootstrap/templates/`**
(see [02-deploy.md](02-deploy.md) "How the template files work"). This SOP is the
permanent version of [90-sop-add-app.md](90-sop-add-app.md): same end result, but the
app lives in the template layer, so it survives every `task configure`.

> If the service's code lives in **its own git repo** (you build the image yourself and
> push it to a registry), use [93-sop-image-to-app.md](93-sop-image-to-app.md) — it ends
> with this SOP, but adds the image/CI half first.

> Rule of thumb: use **this** SOP for any app you want to keep. Use
> [90-sop-add-app.md](90-sop-add-app.md) only for throwaway experiments you plan to
> delete before the next configure (it edits `kubernetes/` directly, which gets
> overwritten).

## 1. Pick a base template

| You want to add… | Copy this template | Why |
|------------------|--------------------|-----|
| Plain docker app, no secrets | `kubernetes/apps/home/joplin/` | simplest app-template shape: one controller, one PVC, one internal ingress |
| Docker app with secrets | `kubernetes/apps/media/lidarr/` | adds `secret.sops.yaml.j2` (Jinja-sourced values) |
| *arr-style media app | `kubernetes/apps/media/sonarr/` | the full pattern: NFS `custom` volumes, exportarr sidecar, grafana dashboard ConfigMap, hajimari icon |
| Real Helm chart | `kubernetes/apps/home/gitea/` (official chart) or `home/grocy/` (k8s-at-home) or `media/piped/` (chart with secrets + external ingress) | non-app-template `values:` |
| Optional/toggleable app ("addon") | `addons/grafana/` + `tasks/addons/grafana.yaml` | has an `enabled:` gate in `bootstrap/vars/addons.yaml` |
| New namespace | copy `kubernetes/apps/media/namespace.yaml.j2` + `kubernetes/apps/media/kustomization.yaml.j2` | the two namespace-level files |

All template files keep their `.j2` suffix — **keep it when you copy**.

```sh
cd bootstrap/templates
cp -r kubernetes/apps/home/joplin kubernetes/apps/<ns>/<app>
# for an addon instead:
cp -r addons/grafana addons/<app>
```

## 2. Edit the copied template

| File | Change |
|------|--------|
| `<app>/ks.yaml.j2` | `metadata.name: cluster-apps-<app>` and `spec.path: ./kubernetes/apps/<ns>/<app>/app`. (Templates are static YAML — no Jinja needed; the name is hardcoded, cf. `sonarr/ks.yaml.j2`.) |
| `<app>/app/kustomization.yaml.j2` | `resources:` — list `./helmrelease.yaml`, and `./secret.sops.yaml` **if** the app has one (commented-out is the "no" state). Keep any `configMapGenerator` block if you ship grafana dashboards. |
| `<app>/app/helmrelease.yaml.j2` | `metadata.name`/`namespace`; `spec.chart` (for app-template: keep chart `app-template` v2.4.0 + `sourceRef bjw-s`, change `values.controllers.main.containers.main.image`); ports/anchors (`&port`, `&host`); `ingress.main` (host `<app>.${SECRET_DOMAIN}`, class `internal` or `external` + external-dns annotation); `persistence` (Longhorn `config` 1–16Gi, or NFS `type: custom` volumes for media); `env`; `secretKeyRef`/`envFrom` for secrets; `probes`. |
| `<app>/app/secret.sops.yaml.j2` (if secrets) | `metadata.name: <app>-secret`; `stringData` keys; **values are Jinja** referencing `bootstrap/vars/config.yaml` — e.g. `api_key: "{{ media_myapp_api_key }}"`. Must render to valid YAML (the sops task parses it with `| from_yaml`). |
| `<app>/app/grafana-dashboards/<name>.json.j2` (optional) | dashboard JSON, listed by the `configMapGenerator` in the app kustomization. |

Two substitution rules to keep straight in HelmRelease values:

- **Flux `${VAR}`** (`${TIMEZONE}`, `${SECRET_DOMAIN}`, `${NFS_TV}`, …) → written
  verbatim; substituted in-cluster at reconcile time. Use these for the standard
  variables (see [03-configuration.md](03-configuration.md)).
- **Jinja `{{ … }}`** → evaluated at `task configure` time, only from
  `bootstrap/vars/config.yaml` / `addons.yaml`. Use this for **new** app-specific
  values (typically inside `secret.sops.yaml.j2`).
- If the app's *own* config syntax uses `{{...}}` (e.g. GetHomepage), wrap it in
  `{% raw %}…{% endraw %}` (see `addons/homepage/app/configmap.yaml.j2`).

## 3. Add new variables to `bootstrap/vars/config.yaml` (if the app has secrets)

`config.yaml` is gitignored plaintext — add e.g.:

```yaml
media_myapp_api_key: "abcdef0123"
```

then reference it in the secret template. No other registration needed — the
sops-encrypt task reads the whole file as Jinja context. (Convention in this repo:
prefix with the area, `media_*` / `home_*` / `grafana.*`.)

## 4. Register the app

- **Existing namespace**: add one line to
  `bootstrap/templates/kubernetes/apps/<ns>/kustomization.yaml.j2`:
  `- ./<app>/ks.yaml`
- **New namespace**: also create the namespace's `namespace.yaml.j2`
  (copy `media/namespace.yaml.j2`, change `metadata.name`; keep the
  `kustomize.toolkit.fluxcd.io/prune: disabled` label) and its
  `kustomization.yaml.j2`.
- **New HelmRepository** (chart not in `kubernetes/flux/repositories/helm/`): add
  `bootstrap/templates/kubernetes/flux/repositories/helm/<repo>.yaml.j2`
  (copy `gitea.yaml.j2` / for OCI copy `bitnami.yaml.j2`) **and** a
  `- ./<repo>.yaml` line in `bootstrap/templates/kubernetes/flux/repositories/helm/kustomization.yaml.j2`.
- **Addon variant** (optional gating): copy
  `bootstrap/tasks/addons/grafana.yaml` → `bootstrap/tasks/addons/<app>.yaml`
  (change the `addon_name` / `addon_namespace` facts), add an
  `include_tasks: <app>.yaml` entry in `bootstrap/tasks/addons/main.yaml` (gate it
  with `when: <app>.enabled | default(false)`), and add a
  `<app>: { enabled: true, … }` block to `bootstrap/vars/addons.yaml`.

## 5. Regenerate, verify, push

```sh
git status                       # start from a clean tree (configure overwrites kubernetes/ + ansible/)
task configure                  # OR: ./deploy.sh "add <app>"  (configure + commit + push in one go)
git diff                        # ← your verification surface:
                                #   1. the new app's files appear under kubernetes/
                                #   2. the ns kustomization gained ./<app>/ks.yaml
                                #   3. *.sops.yaml churn is ciphertext-only (see gotchas)
./scripts/kubeconform.sh kubernetes   # schema-check everything (undefined ${VAR} shows as literal)
# then (if you didn't use deploy.sh):
git add -A && git commit -m "Add <app>" && git push
```

In-cluster confirmation:

```sh
flux get ks -A | grep cluster-apps-<app>     # Ready=True (sops decrypt + build OK)
flux get hr -n <ns> <app>                    # HelmRelease Ready (chart apps)
kubectl -n <ns> get pods,ing -o wide
```

For PRs: the **flux-diff** workflow (`.github/workflows/flux-diff.yaml`) renders the
changed Kustomizations/HelmReleases and posts the in-cluster diff as a comment —
check it before merging.

## Gotchas

- **Keep the `.j2` suffix on everything you copy.** The task pipeline routes files by
  path: anything with `sops` in the name goes through `sops_encrypt`, everything
  else through `template`; the destination name is computed by stripping `.j2`.
  A copied file without the suffix still works, but breaks the convention and the
  `regex_replace('.j2$')` bookkeeping.
- **SOPS churn**: age encryption is non-deterministic (fresh nonce per run), and
  `sops_encrypt` re-encrypts on **every** configure — so `git diff` will show changed
  `ENC[…]`/`lastmodified` in *all* `*.sops.yaml` files even when plaintext is
  unchanged. Review secret diffs by decrypting (`sops --decrypt`), not by eyeballing
  ciphertext.
- **Undefined Jinja var → configure fails** (or, for sops files, produces a broken
  YAML you'll see in the diff). If configure dies mid-run, the output tree may be
  half-written: `git checkout -- kubernetes ansible` and re-run.
- **`-user` vars files are the one protected exception**: `cluster-settings-user.yaml`
  / `cluster-secrets-user.sops.yaml` are only (re)templated if they don't already
  exist. If you need a new *Flux-time* variable used by many apps, add it there
  instead of to the templated files — it survives reconfigures.
- **New apps are public by default only if you say so**: default to
  `className: internal`; use `external` + the external-dns annotation deliberately
  (the whole `frontend/` suite is external + no-auth — don't copy that by accident).
- **Removal is symmetric**: delete the app's template dir, remove its line from the
  namespace kustomization template (and the addon task/include/addons.yaml entry if
  it was an addon), remove any config.yaml vars you added, `task configure`, commit,
  push — `prune: true` deletes the in-cluster resources (PVCs and the Namespace
  survive, as usual).
