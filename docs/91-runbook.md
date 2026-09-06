# 91 — Runbook: Day-2 Operations

## Debugging an app

Standard order (from the template README, adjusted):

```sh
# 1. Flux health for everything the app depends on
flux get sources git,oci -A          # GitRepository / OCIRepository ready?
flux get ks -A                       # Kustomizations: Ready=True? Suspended=False?
flux get hr -A                       # HelmReleases: Ready? LastHandledRevision?

# 2. Is the Kustomization for the app ready? (shows errors, e.g. sops/variable failures)
flux get ks -n flux-system cluster-apps-<app> -o yaml | yq .status

# 3. Pods
kubectl -n <ns> get pods -o wide
kubectl -n <ns> describe pod <pod>          # events: ImagePull, probe failures, PVC pending…
kubectl -n <ns> logs <pod> -f --tail=100
# or fuzzy:  stern -n <ns> <name>

# 4. Service / Ingress
kubectl -n <ns> get svc,ing -o wide
kubectl -n <ns> get ingress <ingress>       # ADDRESS set? ENDPOINTS non-empty?
# 503 from the ingress = no ready endpoints (check pod readiness)

# 5. Namespace events
kubectl -n <ns> get events --sort-by='.lastTimestamp'
```

**Surgical apply** (skip the git round-trip, e.g. to test a change):

```sh
task flux:apply path=<ns>/<app>     # flux build + kubectl apply --server-side
```
⚠ Flux will re-reconcile from git on the next interval and revert any drift.

**Debug pod with a PVC mounted** (data problems):

```sh
task kubernetes:mount ns=<ns> claim=<pvc-name>   # interactive pod with the claim at /config
```

## Common failure patterns

| Symptom | Likely cause / fix |
|---------|--------------------|
| `ks` stuck `Reconciliation in progress` | kustomize build failing — usually an undefined `${VAR}` (check `cluster-settings*`/`cluster-secrets*`) or sops decryption failure (is `sops-age` in flux-system intact? is `age.key` current with `.sops.yaml`?) |
| `HelmRelease` `InstallFailed` / `UpgradeFailed` | chart values invalid for the pinned version; check `flux get hr <name> -o yaml` status; bump/fix `values`; `remediation.retries: 3` auto-retries uninstalls-and-reinstalls |
| `Pending` pod, `FailedMount` | NFS server unreachable (192.168.1.30) or Longhorn PVC not bound (StorageClass missing — default is `longhorn`) |
| `ImagePullBackOff` | tag no longer exists (renovate bumped past a published tag), or registry auth; check the tag in the HelmRelease |
| Ingress `503` but pod Running | probe path/port mismatch (app moved its default port) — check `probes` + `service` in the HelmRelease |
| App works in LAN, broken on phone | split DNS not applied (Pi-hole `server=/jesseeisageek.com/192.168.1.23`), or the app uses `className: internal` but you expected public |
| Public app 403/525 via Cloudflare | TLS: public traffic is terminated at Cloudflare; the cluster-side cert is only for the tunnel hop. Check `cloudflared` pods + `external-dns` record exists (`dig external.jesseisageek.com`) |
| `CrashLoopBackOff` | `kubectl logs` + `describe`; OOM? (check `resources.limits.memory`), bad env (sops secret key name mismatch), missing config file |
| cert-manager `Certificate` not ready | DNS-01 challenge failing → Cloudflare token scope/permissions, or ACME rate limit (staging vs production); `kubectl -n cert-manager get certs,orders,challenges` |
| Flux not reconciling at all | webhook down? `kubectl -n flux-system get receiver,svc`; otherwise it polls every 30m regardless |

## Updates

- **Renovate**: runs Saturdays (`.github/renovate.json5`), opens PRs for chart versions,
  container images, GitHub actions, Ansible roles; auto-merges action minor/patch. Merge →
  Flux applies. The dependency dashboard issue tracks everything.
- **Manual version bump**: edit `spec.chart.spec.version` in the HelmRelease (+ `tag:` in
  image-based apps) → push → `flux get hr` flips.
- **k3s/k0s distribution upgrade**: change the version in
  `ansible/inventory/group_vars/kubernetes/` (or the bootstrap template) →
  `task ansible:run playbook=cluster-rollout-update` (nodes drain/upgrade one at a time).
- **Flux itself**: `kubernetes/flux/config/flux.yaml` pins the `flux-manifests` OCI tag
  (v2.2.2); bump the tag to upgrade, then `task flux:reconcile`.

## Webhook (push → instant reconcile)

```sh
kubectl -n flux-system get receiver github-receiver -o jsonpath='{.status.webhookPath}'
# full URL:  https://flux-webhook.jesseisageek.com/hook/<that-path>
# GitHub → Settings → Webhooks → Add webhook → POST, "active" events: push (+ ping),
#         secret = bootstrap_flux_github_webhook_token
```
Only works once the **production** cert is in place (public ingress path).

## Secrets

- View/rotate: `sops --decrypt <file>` / decrypt→edit→`task sops:encrypt file=<file>`→commit.
  `SOPS_AGE_KEY_FILE=./age.key` is set by `.envrc`.
- **`age.key` lost**: regenerate `task sops:age-keygen`, update `bootstrap_age_public_key`
  in `bootstrap/vars/config.yaml`, re-encrypt **every** `.sops.yaml` (sops files are bound
  to the public key), `task configure`, push, and re-apply `sops-age` to the cluster:
  `cat age.key | kubectl -n flux-system create secret generic sops-age --from-file=age.agekey=/dev/stdin --dry-run=client -o yaml | kubectl apply -f -`.
  (You can also just decrypt, re-encrypt, and let Flux re-create secrets — the k8s Secrets
  are created from the decrypted manifests, so they update automatically.)

## Cloudflare

- Tunnel status: `kubectl -n network get pods -l app.kubernetes.io/name=cloudflared`
  (2 replicas), `kubectl -n network logs <pod>`.
- Tunnel config is `cloudflared-configmap` (generated from `app/configs/config.yaml`);
  creds are the `credentials.json` key of `cloudflared-secret`.
- Rotate tunnel/token: Cloudflare dashboard → update `bootstrap/vars/config.yaml`
  (`bootstrap_cloudflare_tunnel_*`, `bootstrap_cloudflare_token`) → `task configure` → push
  (regenerates `cloudflared-secret`, `external-dns-secret`, `cert-manager-secret`).
- Public DNS: `external-dns` manages `*.jesseisageek.com` CNAMEs; verify with
  `dig external.jesseisageek.com` / `dig <app>.jesseisageek.com`.

## Storage (Longhorn)

- Recurring jobs (in `storage/longhorn/recurring-jobs/`): **snapshot-daily** (05:00),
  **volume-trim-daily** (06:00), **backup-weekly** (Sat 07:00, backup target from values).
- UI: `kubectl -n longhorn-system port-forward --address localhost --tcp 9001:9001`
  (enable `UI.enabled` in the HelmRelease values if not enabled) or use the kubectl plugins.
- Data on PVCs: Longhorn volumes live on node disks; NFS media lives on 192.168.1.30.

## Destructive operations

| Action | Command |
|--------|---------|
| Nuke cluster (wipe k3s + reboot nodes) | `task ansible:run playbook=cluster-nuke` → then stages 5–6 of [02-deploy.md](02-deploy.md) |
| k0s variant | `task k0s:reset` |
| Regenerate `ansible/`+`kubernetes/` from bootstrap (⚠ overwrites) | `task configure` |
| Delete generated dirs (keeps bootstrap/) | `task repo:reset` |
| Delete generated dirs + hard-reset git | `task repo:reset-repo` |
| Power off all nodes | `task ansible:poweroff` |

## Usefulness checklist

```sh
task kubernetes:resources      # nodes, sources, ks, hrs, certs, ingresses, pods
task ansible:ping              # node reachability
flux get all -A                # full flux state
```
