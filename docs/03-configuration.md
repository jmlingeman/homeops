# 03 — Configuration

Three layers of settings, in order of "how close to the metal":

1. **`bootstrap/vars/*.yaml`** (gitignored, plaintext) — the source of truth for everything
   that gets templated into `ansible/` and `kubernetes/`. Regenerate with `task configure`.
2. **`ansible/`** (generated) — inventory + group_vars for the Ansible playbooks only.
3. **`kubernetes/flux/vars/`** — `cluster-settings` / `cluster-secrets` (±`-user`): the
   **Flux-time** variable sources used for `${…}` substitution inside `kubernetes/`.

## 3.1 `bootstrap/vars/config.yaml`

Template-provided keys (current values for this cluster):

| Key | Value | Meaning |
|-----|-------|---------|
| `bootstrap_distribution` | `k3s` | `k3s` or `k0s` (k0s changes playbooks + k0s-config generation) |
| `bootstrap_github_username` / `_repository_name` / `_repository_branch` | `jmlingeman` / `homeops` / `main` | repo identity → GitRepository url, webhook, renovate |
| `bootstrap_age_public_key` | `age1tew57…` | Age public key used by `.sops.yaml` creation rules |
| `bootstrap_timezone` | `America/New_York` | → `cluster-settings.TIMEZONE` + node timezone |
| `bootstrap_acme_email` | `jesse@jesseisageek.com` | → `cluster-secrets.SECRET_ACME_EMAIL`, cert-manager issuers |
| `bootstrap_acme_production_enabled` | `true` | production vs staging Let's Encrypt for the wildcard cert |
| `bootstrap_flux_github_webhook_token` | `e128fd…` | → `github-webhook-token-secret` (sops) |
| `bootstrap_cloudflare_domain` | `jesseisageek.com` | → `cluster-secrets.SECRET_DOMAIN` (all ingress hosts) |
| `bootstrap_cloudflare_token` | `h3WFVR…` | → `cert-manager-secret` + `external-dns` secrets (sops) |
| `bootstrap_cloudflare_account_tag` / `_tunnel_secret` / `_tunnel_id` | `5be0aa…` / `i04mDE…` / `dd05423d-…` | → `cloudflared-secret` (sops: TUNNEL_ID, TUNNEL_TOKEN, TUNNEL_SECRET) |
| `bootstrap_node_cidr` | `192.168.1.0/24` | → `cluster-settings.NODE_CIDR` |
| `bootstrap_kubeapi_addr` | `192.168.1.22` | kube-vip VIP → `cluster-settings.KUBEAPI_ADDR` |
| `bootstrap_k8s_gateway_addr` | `192.168.1.23` | k8s-gateway LB IP |
| `bootstrap_external_ingress_addr` | `192.168.1.24` | nginx-external LB IP |
| `bootstrap_internal_ingress_addr` | `192.168.1.25` | nginx-internal LB IP |
| `bootstrap_cilium_loadbalancer_mode` | `dsr` | `dsr` (default) or `snat` |
| `bootstrap_ipv6_enabled` | `false` | (advanced) |
| `bootstrap_cluster_cidr` / `bootstrap_service_cidr` | `10.42.0.0/16` / `10.43.0.0/16` | → `cluster-settings.{CLUSTER,SERVICE}_CIDR` |
| `bootstrap_local_storage_path` | `/var/openebs/local` | openebs-hostpath mount |
| `bootstrap_nodes.master[]` | `kube-controller` @192.168.1.20 (user `jesse`) | → ansible inventory |
| `bootstrap_nodes.worker[]` | `kube-worker` @192.168.1.21 (user `jesse`) | → ansible inventory |

**Custom (non-template) keys** added in this repo (consumed by templates added here or by
`.envrc`/Ansible directly):

| Key | Value | Used by |
|-----|-------|---------|
| `grafana.password` | `090si0…` | `bootstrap/tasks/addons/grafana.yaml` → grafana sops secret (addon, but grafana here is in `kubernetes/` — see note below) |
| `database_postgresql_hostname/username/password` | `postgres.${SECRET_DOMAIN}` / `dbadmin` / `0aug0s…` | `database/postgresql` HelmRelease values (host, user, sops secret) |
| `domain_name` | `jesseisageek.com` | (redundant with `bootstrap_cloudflare_domain`) |
| `media_nfs_host` | `192.168.1.30` | *arr/piped NFS volumeSpec (many manifests **hardcode** this instead of `${NFS_SERVER}`) |
| `media_nfs_{tv,tv2,movies,music,backup,temp,vaultwarden,audiobooks,downloads}_path` | `/mnt/pool{1,2}/…` | NFS share paths for the media stack |
| `media_sonarr_api_key` | `698881…` | sonarr (API for exportarr/overseerr) |
| `media_postgres_user/password` | `piped` / `0ai9eg…` | piped (its own postgres) |
| `minio_root_user/password` | `admin` / `0984u6…` | (declared; no minio app currently deployed) |
| `plex_url` / `plex_token` | `192.168.1.40` / `kc6CwB…` | (declared for a future plex companion; jellyfin is external) |
| `media_deezer_arl_token` | `fe499e…` | (declared; for Deezer ARL use) |
| `home_firefly3_app_key` / `home_firefly3_db_name` / `home_firefly3_access_token` / `home_firefly3_cron_token` | … | firefly-iii sops secret (`API_KEY`, `POSTGRES_DB`, …) |
| `homarr-db-encryption-key` | `09043j…` | (commented out / unused) |

⚠ These custom keys are **plaintext in a gitignored file** — `config.yaml` never leaves the
workstation (it is gitignored; only the *encrypted* output is committed).

## 3.2 `bootstrap/vars/addons.yaml`

Optional add-on toggles (all gitignored). Current state:

| Addon | Enabled | Generated to |
|-------|---------|--------------|
| `homepage` | ✅ | `kubernetes/apps/default/homepage` |
| `grafana` | ✅ (password in file) | `kubernetes/apps/observability/grafana` |
| `kube_prometheus_stack` | ✅ | `kubernetes/apps/observability/kube-prometheus-stack` |
| `kubernetes_dashboard` | ✅ | `kubernetes/apps/observability/kubernetes-dashboard` |
| `weave_gitops` | ❌ | — |
| `csi_driver_nfs` | ❌ | — (repo declared in flux/repositories/helm) |
| `system_upgrade_controller` | ❌ | — (k3s-only) |
| `discord_template_notifier` | ❌ | — |
| `volsync` | ❌ | — |

(Also always generated for k3s: the `coredns` app.)

## 3.3 Flux substitution variables (`kubernetes/flux/vars/`)

`postBuild.substituteFrom` in `kubernetes/flux/apps.yaml` + `config/cluster.yaml` makes these
available as `${KEY}` in any manifest under `kubernetes/` (Kustomize-style variable
substitution done by the kustomize-controller after sops decryption):

`cluster-settings` (ConfigMap, plain):

| Key | Value |
|-----|-------|
| `TIMEZONE` | `America/New_York` |
| `COREDNS_ADDR` | `10.43.0.10` |
| `KUBEAPI_ADDR` | `192.168.1.22` |
| `CLUSTER_CIDR` | `10.42.0.0/16` |
| `SERVICE_CIDR` | `10.43.0.0/16` |
| `NODE_CIDR` | `192.168.1.0/24` |

`cluster-secrets` (Secret, sops-encrypted — values below, key names visible):

| Key | Value |
|-----|-------|
| `SECRET_DOMAIN` | `jesseisageek.com` |
| `SECRET_ACME_EMAIL` | `jesse@jesseisageek.com` |
| `SECRET_CLOUDFLARE_TUNNEL_ID` | `dd05423d-…` (UUID — full value only in the sops secret / `config.yaml`) |
| `NFS_SERVER` | `192.168.1.30` |
| `NFS_TV` | `/mnt/pool1/tv` |
| `NFS_TV2` | `/mnt/pool2/tv` |
| `NFS_MOVIES` | `/mnt/pool2/movies` |
| `NFS_MUSIC` | `/mnt/pool2/music` |
| `NFS_BACKUP` | `/mnt/pool1/backup` |

> Values above are the ones templated from `bootstrap/vars/config.yaml` (the SOPS file itself
> is encrypted; decrypt with `sops --decrypt` + `age.key` to confirm at any time).

`cluster-settings-user` (ConfigMap) and `cluster-secrets-user` (Secret) exist but only
contain placeholders (`SETTINGS_PLACEHOLDER` / `SECRET_PLACEHOLDER`) — they are the intended
**personal** layer for new variables you add after bootstrap (not regenerated by
`task configure`).

### Substitution rules & gotchas

- `${VAR}` works in **all** YAML under `kubernetes/` (Flux kustomize-controller
  `postBuild.substitute`), including sops-encrypted files (decryption runs first).
- `${VAR/./-}` and other kustomize-style transforms work (e.g.
  `${SECRET_DOMAIN/./-}-production` → `jesseisageek-com-production`).
- If a variable has **no** value anywhere, the Kustomization fails to build — check
  `cluster-settings*`/`cluster-secrets*`.
- Unsubstituted `${…}` in a committed file will show up in `flux-local` diff / kubeconform
  output as literal `${…}` strings — a good canary.
- `.envrc` exports `NFS_SERVER`/`NFS_TV` etc. for the **workstation** (Ansible SOPS lookups);
  cluster-side substitution comes from the k8s ConfigMap/Secret, not the shell.

## 3.4 Ansible (`ansible/inventory/`)

- `hosts.yaml`: `kubernetes: {master: kube-controller(192.168.1.20), worker: kube-worker(192.168.1.21)}`,
  `ansible_user: jesse`.
- `group_vars/kubernetes/main.yaml` (generated from config.yaml): kube-vip, cilium mode,
  cidrs, k3s version vars, etc.
- `group_vars/kubernetes/supplemental.yaml`: extra k3s args/env.
- `host_vars/`: per-host overrides (empty; `.gitkeep`).
- `sops` vars plugin: `ANSIBLE_VARS_ENABLED=host_group_vars,community.sops.sops` — Ansible can
  read `*.sops.yaml` host/group vars with the age key (used by playbooks, e.g. for the
  kube-vip config).

## 3.5 Where to change what

| I want to… | Edit |
|------------|------|
| Change a node IP / add a node | `bootstrap/vars/config.yaml` → `task configure` → re-run ansible |
| Change domain / cloudflare token / tunnel | `bootstrap/vars/config.yaml` → `task configure` → push (sops files re-encrypted; check `git diff` shows encrypted-only changes) |
| Change an ingress host suffix for all apps | `${SECRET_DOMAIN}` comes from `cluster-secrets.SECRET_DOMAIN` — change via `task configure`, or for one app only edit its `helmrelease.yaml` host |
| Add a variable used by new apps | `cluster-settings-user.yaml` (non-secret) or `cluster-secrets-user.sops.yaml` (secret) in `kubernetes/flux/vars/` |
| Change app behavior (env, ports, resources, volumes) | the app's `kubernetes/apps/<ns>/<app>/app/helmrelease.yaml` (or extra files listed in its `app/kustomization.yaml`) |
| Change the chart version / chart repo | `helmrelease.yaml` → `spec.chart.spec.{version,sourceRef}` (+ `kubernetes/flux/repositories/helm/` if a new repo) |
| Change k3s version / system packages | `ansible/inventory/group_vars/kubernetes/main.yaml` (generated — or its template) |
| Timezone | `bootstrap/vars/config.yaml` (`bootstrap_timezone`) → `task configure` |
