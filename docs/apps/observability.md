# observability

## grafana

Grafana (chart `grafana` 7.0.19, grafana repo):

- **Ingress**: `grafana.${SECRET_DOMAIN}` (internal).
- **Auth**: admin from `grafana-admin-secret` sops secret (`admin-user`,
  `admin-password` — from `bootstrap/vars/addons.yaml` `grafana.password`).
- **Dashboards**: sidecar scrapes any ConfigMap labeled
  `grafana_dashboard: "1"` across all namespaces (the *arr apps generate these:
  `grafana-dashboards-sonarr` / `grafana-dashboards-radarr`), folders default/flux/
  kubernetes/nginx; `GF_SERVER_ROOT_URL` set, explore enabled, update checks off.
- **Datasource**: Prometheus at `kube-prometheus-stack-prometheus.observability.svc:9090`.
- **Persistence**: `openebs-hostpath` (no size set).
- **dependsOn**: `openebs` (storage ns).
- Homepage widget with `HOMEPAGE_VAR_GRAFANA_*` from the homepage secret.

## headlamp

Headlamp web UI (chart `headlamp` 0.45.0, `https://kubernetes-sigs.github.io/headlamp/`
— the project moved to `kubernetes-sigs/headlamp`; image is still
`ghcr.io/headlamp-k8s/headlamp:v0.45.0`). CNCF Sandbox / SIG UI; the kubernetes.io
recommended replacement for kubernetes-dashboard (blog 2026-07-13).

- **Ingress**: `headlamp.${SECRET_DOMAIN}` (internal, homepage tile).
  Unlike kubernetes-dashboard the chart creates no ingress — ours is a standalone
  `app/ingress.yaml` pointing at the chart's `headlamp` Service, port named `http`.
- **Auth**: none by default (open, like kubernetes-dashboard) → same ⚠ trusted-LAN
  only warning. The chart supports OIDC (`config.oidc`) when you want login.
- **Access**: `config.inCluster: true` → uses its own ServiceAccount, bound to
  **cluster-admin** by the chart's ClusterRoleBinding (no extra values set in the
  HelmRelease; defaults are correct).
- **What it shows that k8s-dashboard doesn't**: per-pod live logs,
  previous-container logs (crash cause), exec terminal, events, YAML editor,
  cluster map view, plugin system (Artifact Hub).
- **No persistence**: stateless.

## kube-prometheus-stack

Prometheus monitoring stack (chart `kube-prometheus-stack` 55.8.1,
prometheus-community **OCI** repo):

- **Prometheus**: 10Gi `openebs-hostpath` (retentionSize 8GiB); ServiceMonitors for
  kubelet / kube-scheduler / kube-controller-manager / kube-apiserver (k3s
  endpoints hardcoded to 192.168.1.20) + kube-state-metrics (PodMonitor,
  `metricLabelsAllowlist`).
- **Ingress**: `prometheus.${SECRET_DOMAIN}` (internal).
- **Disabled**: alertmanager (no notification channel configured → the
  cert-manager/mixin `PrometheusRule`s collect but go nowhere), kubeEtcd (k3s etcd
  not exposed), kubeProxy (eBPF), the Grafana subchart (`forceDeployDashboards: true`
  still deploys the dashboards into the separate `grafana` release).
- **CRDs**: `CreateReplace` on install/upgrade (prometheus-operator CRDs also
  pre-applied by `task flux:bootstrap`).
- **Values live in a ConfigMap** `kube-prometheus-stack-values`
  (`app/helmvalues.yaml` → `valuesFrom`) rather than inline — the kps `helmvalues.yaml`
  is the biggest values file in the repo; edit it there, not in the HelmRelease.
- **dependsOn**: `openebs`.

## kubernetes-dashboard

K8s web UI (chart `kubernetes-dashboard` 6.0.8, kubernetes.github.io):

- **Ingress**: `kubernetes.${SECRET_DOMAIN}` (internal).
- **⚠ Security note**: `--enable-skip-login --enable-insecure-login
  --disable-settings-authorizer` → **no authentication**; reachable by anything on
  the internal ingress, and `rbac.yaml` binds the dashboard's ServiceAccount to
  **cluster-admin**. Fine on a trusted LAN, but don't ever put this app on the
  external class.
- `app/rbac.yaml` also holds a ServiceAccount-token `Secret`
  (`kubectl -n observability get secret kubernetes-dashboard`) for manual kubectl.
- **dependsOn**: `cert-manager`, `metrics-server`.

## Local terminal tools (not cluster apps)

Installed on the workstation, not in the cluster — use with the repo's
`kubeconfig` (direnv loads it):

- **k9s** — TUI kubectl. `k9s` → pod view shows phase/restarts/OOMKilled;
  `l` logs, `l p` previous-container logs, `e` events. Installed to
  `~/.local/bin/k9s` (release tarball, GitHub derailed/k9s).
- **kutop** — btop-style TUI: pods/nodes with restart counts, OOMKilled,
  warning events, PVC usage, Alertmanager alerts. `pip`/`uv tool install kutop`
  (GitHub ken-jo/kutop); also ships `kubetop` (the original).
