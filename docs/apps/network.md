# network

Ingress, DNS, tunneling — the traffic edge of the cluster.

## nginx (3 Kustomizations in one `ks.yaml`)

Two ingress-nginx controllers (chart `ingress-nginx` 4.7.1, repo `ingress-nginx`):

- **`nginx-internal`** (default class `internal`, controllerValue `k8s.io/internal`):
  LB `192.168.1.25`, external-dns hostname `internal.${SECRET_DOMAIN}` — the LAN entry
  point (split-DNS resolves the domain here).
- **`nginx-external`** (class `external`, controllerValue `k8s.io/external`):
  LB `192.168.1.24`, external-dns hostname `external.${SECRET_DOMAIN}` — the
  Cloudflare-tunnel entry point.
- **`nginx-certificates`** (dependsOn `cert-manager-issuers`): the `Certificate`
  `jesseisageek.com` + `*.jesseisageek.com` (production + staging files in
  `certificates/`; production secret `jesseisageek-com-production-tls` is the
  `extraArgs.default-ssl-certificate` of both controllers).

Both: `client-max-body-size 0`, JSON logging, TLS 1.2/1.3, serviceMonitor
(any-namespace), `topologySpreadConstraints` maxSkew 1 (one per node),
10m/250Mi requests / 500Mi limit.

## k8s-gateway

DNS server for the domain (chart `k8s-gateway` 2.1.0, repo k8s-gateway/ori-edge):
LoadBalancer service on port 53 with `io.cilium/lb-ipam-ips: 192.168.1.23`,
`domain: ${SECRET_DOMAIN}`, ttl 1. Home DNS (Pi-hole) forwards
`/jesseisageek.com/` to this IP (split DNS) — this is how LAN devices resolve
`*.jesseisageek.com` to 192.168.1.25.

## external-dns

Syncs Cloudflare DNS records (chart `external-dns` 1.14.1, repo external-dns):
provider `cloudflare` (token from `external-dns-secret/api-token`, sops),
`--ingress-class=external --crd-source --cloudflare-proxied`,
`domainFilters: ${SECRET_DOMAIN}`, sources = ingresses + `DNSEndpoint` CRD (v1alpha1,
pre-installed by `app/dnsendpoint-crd.yaml`). The reloader pod annotation reloads on
secret change. The **cloudflared**, **echo-server**, **gitea**, **piped**, **grocy**,
**vaultwarden** ingresses use its `external-dns.alpha.kubernetes.io/target`
annotation.

## cloudflared

Cloudflare tunnel (app-template, image `docker.io/cloudflare/cloudflared:2024.1.2`,
2 replicas, QUIC + post-quantum). Config in `cloudflared-configmap`
(`configs/config.yaml`: `*.${SECRET_DOMAIN}` + apex →
`https://nginx-external-controller.network.svc:443` with SNI
`external.${SECRET_DOMAIN}`); creds in `cloudflared-secret` (`credentials.json` +
`TUNNEL_ID` keys, sops). `/ready` probes on 8080, serviceMonitor,
`runAsUser/Group 568`. This is the only path from the internet into the cluster.

## echo-server

Public test endpoint (app-template, `jmalloc/echo-server:0.3.6`, 2 replicas):
echoes HTTP back to the caller; class `external` + external-dns target →
`echo-server.jesseisageek.com`. Used to verify tunnel/public-DNS health. Homepage
widget (group Network).
