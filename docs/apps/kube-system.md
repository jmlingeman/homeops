# kube-system

Cluster networking and DNS plumbing.

## cilium

CNI + service-mesh-free networking layer (chart `cilium` 1.14.5, repo `cilium`).
Replaces kube-proxy (MAGLOAD/DSR L4 LB, `bootstrap_cilium_loadbalancer_mode: dsr`),
provides **L2 announcements** (so the static VIPs 192.168.1.22–.25 work as
LoadBalancers) and runs **Hubble** (observability).

- **Ingress**: `hubble.${SECRET_DOMAIN}` (class `internal`) → Hubble UI
  (homepage widget, icon `cilium.png`).
- **Files**: `app/helmrelease.yaml`, `app/helmvalues.yaml` (ConfigMap `cilium-values`
  via `valuesFrom`), `app/cilium-l2.yaml` (`CiliumL2AnnouncementPolicy` +
  `CiliumLoadBalancerIPPool` over `${NODE_CIDR}`).
- **Notes**: Kustomization has `prune: false` ("never should be deleted"); values use
  `${SECRET_DOMAIN}`, `${CLUSTER_CIDR}`, `${KUBEAPI_ADDR}`, `${NODE_CIDR}`. Prometheus
  enabled for agent/operator/hubble-relay (serviceMonitors), Grafana dashboards
  (`grafana_folder: Cilium`).

## coredns

Cluster DNS (chart `coredns` 1.29.0, repo `coredns`): `kube-dns` ClusterIP pinned to
`${COREDNS_ADDR}` (10.43.0.10), Corefile via ConfigMap with the reloader
annotation (auto-reload on Corefile change), single replica pinned to the
control-plane node with tolerations + topology spread. Metrics on :9153.
`prune: false` on the Kustomization.

## metrics-server

`kubectl top` / HPA source (chart `metrics-server` 3.11.0): kubelet scraping at 15s,
`--kubelet-insecure-tls`, serviceMonitor enabled. No ingress, no persistence.
