# 02 — Deployment (from scratch)

The cluster is provisioned in six stages. All commands run on the **workstation** from the repo
root, with `direnv` active (see `.envrc`). The original template README
([README.md](../README.md) stages 1–6) has the full narrative; this is the condensed,
repo-specific version. This cluster currently runs **k3s** (1 master `kube-controller` +
1 worker `kube-worker`).

## Prerequisites

- Workstation tools: `task` (go-task), `direnv` (+ `direnv allow`), `age`, `sops`, `flux`,
  `cloudflared`, `kubectl`, `python3` (3.10+).
  `task workstation:brew` / `workstation:yay` installs them; `task ansible:deps` builds
  `.venv` with Ansible 9.1 + galaxy roles (`requirements.yaml`: `xanmanning.k3s`,
  `community.sops`, `ansible.posix`, …).
- Nodes: Debian 12, SSH reachable as `jesse` **without passphrase** (agent).
- A domain on Cloudflare (`jesseisageek.com`) with an API token
  (Zone DNS:Edit + Tunnel:Read) and a Cloudflare **tunnel** created
  (`cloudflared tunnel login && cloudflared tunnel create k8s`).
- A DNS box (Pi-hole etc.) outside the cluster doing split DNS
  (`server=/jesseisageek.com/192.168.1.23`).

## Stage 1 — Repo

This repo (`github.com/jmlingeman/homeops`, branch `main`) is the flux-cluster-template
fingerprinted for this cluster (user `jmlingeman`, domain `jesseisageek.com`).

## Stage 2 — Workstation

```sh
task workstation:brew      # or workstation:yay
task ansible:deps          # creates .venv (ansible 9.1, galaxy roles)
```

## Stage 3 — Bootstrap configuration

```sh
task init        # copies vars/*.sample.yaml → vars/*.yaml (cp -n: no overwrite)
# edit bootstrap/vars/config.yaml  (gitignored — contains plaintext secrets)
# edit bootstrap/vars/addons.yaml  (gitignored — addon toggles)
task sops:age-keygen   # generates age.key (gitignored) + prints age.pub
task configure         # runs bootstrap/configure.yaml → validates, then templates ./ansible + ./kubernetes
```

What `task configure` generates (from `bootstrap/templates/`):

- `.sops.yaml` (creation rules with your age.pub)
- `ansible/` — inventory (`hosts.yaml`, group_vars) + k3s playbooks
- `kubernetes/` — the entire cluster definition (flux config, repos, vars, apps)
- `k0s-config.yaml` (only if `bootstrap_distribution: k0s`)

Validation (`bootstrap/tasks/validation/`) checks: required CLI tools present, age pub/private
pair match, cloudflare account tag/tunnel id, node CIDR sanity, domain/A-record reachability.

**This cluster's actual config** (values below from `bootstrap/vars/config.yaml` — see
[03-configuration.md](03-configuration.md) for the full list): k3s, ACME production enabled,
cloudflare tunnel `dd05423d-…`, VIPs .22/.23/.24/.25, nodes .20/.21, NFS at 192.168.1.30.

### How the template files work

The templates are **Jinja2 files processed by Ansible** — `task configure` is just
`ansible-playbook bootstrap/configure.yaml` run against `localhost` (no cluster
involved). The playbook:

1. Loads `bootstrap/vars/config.yaml` + `bootstrap/vars/addons.yaml` as `vars_files`
   (these gitignored files are the *only* input — everything else is derived).
2. Runs `tasks/validation/` (CLI tools, age keypair match, Cloudflare, network) and
   aborts on failure.
3. Walks the template trees with `community.general.filetree` and handles every file
   by class (the `.j2` suffix is just a marker — **most templates contain no Jinja at
   all** and are copied verbatim, e.g. the *arr HelmReleases):

   | Template path | Class | Output |
   |---------------|-------|--------|
   | `templates/kubernetes/**` (no `sops`, no `-user`) | plain / jinja | `kubernetes/…` (`.j2` stripped) — via `ansible.builtin.template` |
   | `templates/kubernetes/**/*-user*` | plain / jinja | `kubernetes/flux/vars/cluster-{settings,secrets}-user.*` — **templated only if the output doesn't already exist** (protects your post-bootstrap additions) |
   | `templates/**/*sops*.j2` | jinja → **sops** | the file is rendered in memory (`lookup('template')\|from_yaml`), then `community.sops.sops_encrypt` writes it with `data`/`stringData` encrypted by your age pub key — so `cluster-secrets.sops.yaml` etc. are *re-encrypted from plaintext on every run* (the plaintext never lands on disk) |
   | `templates/ansible/{shared,<distro>}/` | plain / jinja / sops | `ansible/` (inventory, group_vars, playbooks) |
   | `templates/.sops.yaml.j2` | jinja | repo-root `.sops.yaml` (creation rules + age pub key) |
   | `templates/k0s/k0s-config.yaml.j2` | jinja | `k0s-config.yaml` (only when `bootstrap_distribution: k0s`) |
4. Runs `tasks/addons/`: each optional addon (coredns, homepage, grafana,
   kube-prometheus-stack, kubernetes-dashboard, …) has its own task file, gated by
   `<addon>.enabled` in `bootstrap/vars/addons.yaml`; each walks
   `templates/addons/<addon>/` → `kubernetes/apps/<ns>/<addon>/` with the same
   plain/jinja/sops rules. (`coredns` is unconditional for k3s.)

**Two different substitution layers** — easy to confuse:

- **Jinja `{{ bootstrap_* }}`** — evaluated by Ansible *at configure time* from
  `bootstrap/vars/*.yaml`. Only a few templates use it (cluster-settings/secrets,
  `.sops.yaml`, ansible inventory, k0s config, a few app templates).
- **Flux `${VAR}`** — left as-is in the generated files; substituted **in-cluster at
  reconcile time** by the kustomize-controller from the `cluster-settings*` /
  `cluster-secrets*` ConfigMap/Secret (see [03-configuration.md](03-configuration.md)).

**Overwrite semantics**: `task configure` (`force: true`) rewrites every templated
file, and in this fork **every app under `kubernetes/apps/` has a template**
(including the addons' five: homepage, coredns, grafana, kube-prometheus-stack,
kubernetes-dashboard). So hand-edits to `kubernetes/` or `ansible/` are **lost on the
next configure** — to make a change permanent, edit the template (or the
`*-user*` files, which survive once created), or use `deploy.sh` — the
nuke-and-regenerate path. For the full workflow of turning a template into a new
app, see [92-sop-add-app-from-template.md](92-sop-add-app-from-template.md). Verbatim:

```sh
REPO="$(git rev-parse --show-toplevel)" || exit 1
rm -rf "$REPO/kubernetes" && task configure && git add "$REPO" && git commit -a -m "$1" && git push
```

Note the details:

- `REPO="$(git rev-parse --show-toplevel)" || exit 1` — resolves the repo root
  at run time (the script previously hardcoded `~/Workspace/homeops`, a stale
  earlier checkout location, and its `rm` was a silent no-op). Aborts if not
  run from inside the repo instead of `rm -rf`-ing a bare path.
- `rm -rf "$REPO/kubernetes"` — **wipes the whole generated tree**, then
  `task configure` re-renders it. Consequence: anything you added by hand to
  `kubernetes/` — including `cluster-settings-user.yaml` /
  `cluster-secrets-user.sops.yaml` (those are only re-created from their
  placeholder templates, since the outputs no longer exist) — is gone. Keep
  persistent state in `bootstrap/templates/` (the source of truth) or in
  gitignored `bootstrap/vars/*.yaml`, never in `kubernetes/`.
- `task configure` — regenerates `kubernetes/` (+ `ansible/`, `.sops.yaml`) in
  the repo root.
- `git add "$REPO"` — stages **everything** under the repo root, not just
  `kubernetes/`.
- `git commit -a -m "$1"` — `-a` also stages **all other modified/deleted
  tracked files** in the repo (docs, templates, …), so the commit is
  "everything changed", not just generated files. Requires a non-empty commit
  message as `$1` (`./deploy.sh "message"`), otherwise the commit (and
  therefore the push) fails.
- `git push` — GitHub → Flux `GitRepository` reconcile (webhook if configured,
  else the 30m interval) → cluster updated.

## Stage 4 — Prepare nodes (Ansible)

```sh
task ansible:list
task ansible:ping
task ansible:run playbook=cluster-prepare   # packages, users, ssh keys, NFS client, sysctl… (reboots)
```

## Stage 5 — Install k3s (Ansible)

```sh
task ansible:run playbook=cluster-installation
```

- Installs k3s via the `xanmanning.k3s` role (server on `kube-controller`, agent on
  `kube-worker`), kube-vip static pod on the server (VIP 192.168.1.22), Cilium + CoreDNS as
  k3s system manifests (templates in `ansible/playbooks/templates/`), fetches kubeconfig into
  repo root `kubeconfig`.
- (k0s alternative: `task k0s:apply` — not in use here.)

Verify: `kubectl get nodes -o wide` → both `Ready`.

## Stage 6 — Bootstrap Flux

```sh
flux check --pre
# ensure all *.sops.yaml under kubernetes/ are encrypted:  sops file (see 04-secrets-sops.md)
git add -A && git commit -m "Initial commit :rocket:" && git push
task flux:bootstrap
```

`task flux:bootstrap` (`.taskfiles/Flux/Taskfile.yaml`) does, in order:

1. `kubectl apply` the Prometheus-operator CRDs (PodMonitor, PrometheusRule, ScrapeConfig,
   ServiceMonitor) — needed before Flux installs anything that references them.
2. `kubectl apply --kustomize kubernetes/bootstrap` — installs Flux v2.2.2 (manifests from
   `github.com/fluxcd/flux2/manifests/install?ref=v2.2.2`).
3. Creates `sops-age` Secret in flux-system from `./age.key`.
4. Applies `cluster-secrets.sops.yaml`, `cluster-secrets-user.sops.yaml` (sops-decrypted) and
   the two plain `cluster-settings*.yaml`.
5. `kubectl apply --kustomize kubernetes/flux/config` — the `home-kubernetes` GitRepository +
   `cluster` Kustomization.

Flux then: pulls `kubernetes/` → applies `kubernetes/flux` (HelmRepos, vars, flux self-upgrade
Kustomization) → applies `cluster-apps` (everything in `kubernetes/apps`) → apps light up.

**Post-bootstrap** (one-time, in order):
1. Wait for the Let's Encrypt **staging** wildcard cert, verify internal DNS resolves
   (see README "Post installation"), then flip `bootstrap_acme_production_enabled: true` in
   `bootstrap/vars/config.yaml`, `task configure`, push. (Already done in this repo.)
2. Configure the GitHub webhook (`task kubernetes:resources`; get path from the
   `github-receiver` status; see [91-runbook.md](91-runbook.md)).
3. Optionally `task repo:clean` — moves `bootstrap/` to `.private/`, removes template CI.
   (Not done here — the template is kept because this fork is also a template fork.)

## Re-deploying / rebuilding

| Scenario | Command |
|----------|---------|
| Node OS reinstall / cluster nuke | `task ansible:run playbook=cluster-nuke` (wipes k3s, reboots) → re-run stages 5–6 |
| k0s equivalent | `task k0s:reset` (k0sctl reset + cluster-nuke) |
| Rebuild config files from `bootstrap/` | `task configure` (⚠ overwrites generated dirs) |
| Throw away generated dirs entirely | `task repo:reset` (+ `repo:reset-repo` → `git reset --hard HEAD`) |
| Roll k3s version on all nodes | `task ansible:run playbook=cluster-rollout-update` |
| Reboot all nodes | `task ansible:run playbook=cluster-reboot` |

## CI / validation

- **flux-diff** workflow (`.github/workflows/flux-diff.yaml`): on PRs touching `kubernetes/**`,
  builds the changed kustomizations/helmreleases with `flux-local` (allenporter/flux-local),
  diffs against the default branch, posts the diff as a PR comment. This is the primary
  "what will change" preview — always read it before merging.
- **kubeconform** (`scripts/kubeconform.sh kubernetes`): strict schema validation of all
  `kubernetes/flux` + `kubernetes/apps` kustomizations (kustomize build → kubeconform,
  kubernetes-version 1.29.0, custom CRD schema locations, Secrets skipped). Run locally before
  pushing when in doubt.
- **Renovate** (`.github/renovate.json5`): Saturdays; updates charts, container images,
  GitHub actions, Ansible roles; automerges actions minor/patch.
