# VPN (wireguard / wg-easy)

Two WireGuard addons from [SlyBase/helm-charts](https://github.com/SlyBase/helm-charts)
(OCI: `oci://ghcr.io/slybase/charts`, declared as the `slybase` HelmRepository).
**Both are disabled by default** — enable at most one of them, since they're
alternative VPN servers, not complementary services:

| Addon (`bootstrap/vars/addons.yaml`) | Toggle | What it is | Access |
|--------------------------------------|--------|------------|--------|
| `wireguard` | `wireguard.enabled` | Headless WireGuard server (`linuxserver/wireguard`, s6) — no UI; peer configs generated per name | UDP `192.168.1.20:31822` |
| `wg-easy` | `wg_easy.enabled` | WireGuard with web admin UI (init mode seeds admin creds from the sops secret) | UI `http://192.168.1.20:30201`, UDP `192.168.1.20:30200` |

Both deploy into their **own namespace** (`wireguard` / `wg-easy`), each labeled
`pod-security.kubernetes.io/enforce: privileged` (both charts need NET_ADMIN /
sysctls). Both put their state on a **Longhorn** PVC (`retain`/`resourcePolicy: keep`,
so the peer DB survives app deletion). NodePort traffic arrives on either k3s
node; the templates use `192.168.1.20` (the master) as the advertised address.

## Enabling

```sh
# bootstrap/vars/addons.yaml (gitignored)
wireguard:
  enabled: true        # or wg_easy.enabled: true

./deploy.sh "enable wireguard"   # (task configure + commit + push)
```

- **wireguard**: clients connect to `192.168.1.20:31822` (UDP). Peer config
  files appear as `/config/peer_<name>.conf` in the pod — add peer names to
  `wireguard.server.config.peers` (comma-separated) in
  `bootstrap/templates/addons/wireguard/app/helmrelease.yaml.j2`, then
  `task configure && ./deploy.sh "..."`. Print one from the pod:
  `kubectl -n wireguard exec deploy/wg-wireguard -- cat /config/peer_jesse.conf`
- **wg-easy**: log in to `http://192.168.1.20:30201` with
  `wg_easy.username` / `wg_easy.password` (from `bootstrap/vars/addons.yaml`),
  create VPN profiles there; the admin UI is HTTP-only on the LAN — don't
  expose it publicly.

## Gotchas

- **Don't enable both** — you'd run two VPN servers; pick one. (Enabling both
  technically works: they use different NodePorts and CIDRs, 10.13.13.0/24 vs
  10.8.0.0/24, but it serves no purpose.)
- **wg-easy needs iptables-legacy** — it will CrashLoop on nftables-only
  kernels (e.g. Debian 13+). Check a node with `uname -r` /
  `modprobe iptable_legacy`; if it's not there, use the `wireguard` addon
  instead (linuxserver image, no iptables-legacy dependency) or pin
  `image.tag` to a wg-easy v14 build.
- **wg-easy INIT_PORT quirk** — the chart writes `service.wireguard.port` into
  the client config, so the template sets that value to `30200` (== nodePort);
  don't "clean it up" back to 51820 or generated client configs will point at
  a port nobody listens on externally.
- **Charts** (pinned in the addon HelmReleases): wireguard 2.0.4
  (image `linuxserver/wireguard:1.0.20260223-r0-ls120`), wg-easy 1.2.0
  (image `ghcr.io/wg-easy/wg-easy:15.4.0`, digest-pinned by the chart).
  Bump via `task configure` after editing the `version:` in the addon
  HelmRelease template — `bootstrap/templates/addons/` is not in Renovate's
  fileMatch.
- **Secrets** (wg-easy only): `wg-easy-secret` (username/password) and
  `wg-metrics-secret` (metrics bearer token) are sops-encrypted from
  `bootstrap/templates/addons/wg-easy/app/secret.sops.yaml.j2`; the values
  live under `wg_easy.*` in `bootstrap/vars/addons.yaml`.
- **Metrics**: the wg-easy HR enables the ServiceMonitor + a Grafana
  dashboard ConfigMap (discovered by the kube-prometheus-stack sidecar, same
  `grafana_dashboard` label as the other charts).
