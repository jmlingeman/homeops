# Off-site WireGuard VPN (wg-easy) — how it works and what was fixed

Status: **working** (verified off-site from a phone on cellular — September 2026 client fixes;
October 2026 off-site `*.jesseisageek.com` DNS + load-balancer + Safari fixes;
November 2026: the "external sites dead" outage traced to wg-quick full-tunnel policy routing
(table 51820) in the pod netns — fixed by extending the postStart hook; see the November 2026
incident section below).

Clients connect from anywhere to the home k3s cluster's WireGuard server
(`wg-easy`, v15.4.0, Node-based image) and can reach the home LAN
(`192.168.1.0/24`) through the tunnel: pings, SSH, and internal domains
(`*.jesseisageek.com`, `plex.local`).

## Topology

```
phone (10.8.0.x)                    home
   |  UDP 30200
   v
vpn.jesseisageek.com  (DDNS A -> home WAN IP; DNS-only / unproxied, NOT Cloudflare-proxied)
   |  router port-forward 30200/UDP -> 192.168.1.20:30200   (+ 30201/TCP for the UI)
   v
k3s node (NodePort) -> BPF LB -> wg-easy pod netns (worker)
   |  kernel WireGuard on wg0 (10.8.0.0/24)
   |  phone -> LAN packets: FORWARD (policy ACCEPT) -> MASQUERADE (src -> pod k8s IP)
   v
node -> home router
   |  static routes (LAN side):
   |     10.42.0.0/24 -> 192.168.1.20
   |     10.42.1.0/24 -> 192.168.1.21
   v
LAN machines (plex, sonarr via nginx-internal .25, ...)
   |  replies to the pod's k8s IP
   v  (same static routes, back through the node into the pod netns)
   conntrack un-masquerades -> 10.8.0.x -> wg0 -> phone
```

DNS for internal names: client configs carry `DNS = 192.168.1.23`, which is
the **k8s-gateway split-DNS** service (Cilium LB IP). k8s-gateway is
authoritative for `jesseisageek.com` (internal apps answer with
`192.168.1.25`, the nginx-internal LB) and forwards every other name
upstream. Queries traverse the tunnel. Pi-hole (`192.168.1.10`) is *not*
the right server for `*.jesseisageek.com` names — k8s-gateway is.

## The root causes, in the order they were found

1. **Stale client config on the phone.** The installed config was missing
   `192.168.1.0/24` in `AllowedIPs` (and the `DNS = 192.168.1.23` line).
   WireGuard client routing is defined by the *client-side* config, not the
   server-side peer entry, so the phone sent all `192.168.1.x` traffic out
   its cellular default route (a private subnet — black hole) while the
   tunnel itself looked healthy. **Fix:** re-scan the current QR from the
   UI. Symptom signature: tunnel pings (`10.8.0.1`) fine, LAN pings dead,
   and *zero* packets from the client arriving at the server netns.

2. **Endpoint was a LAN address.** The app's global host was
   `192.168.1.20:30200`. A phone on cellular cannot reach that at all, so
   off-site the tunnel never even establishes (and with no persistent
   keepalive, cellular NAT reaps idle tunnels within minutes).
   **Fix:** router port-forward `30200/UDP -> 192.168.1.20` (and
   `30201/TCP` for the UI), app global **Host = `vpn.jesseisageek.com`**,
   per-client **Persistent Keepalive = 25s**, re-scan. The DDNS record must
   be **DNS-only (grey cloud)** — Cloudflare-proxied would send UDP to
   Cloudflare's edge, and Cloudflare Tunnel doesn't carry UDP, so the
   existing `external.*` tunnel is useless for WireGuard.

3. **Router had no return routes to the k8s pod subnets.** With the
   masquerade, phone traffic leaves the pod with the pod's k8s IP
   (`10.42.x.y`). LAN machines reply to that address, which their default
   gateway (the consumer router) had no route for. **Fix:** two static
   routes on the router, **LAN side** (the router form is
   destination / subnet mask / gateway):
   `10.42.0.0 / 255.255.255.0 / 192.168.1.20` and
   `10.42.1.0 / 255.255.255.0 / 192.168.1.21`.
   **Do not** add a route for `10.8.0.0/24` — the nodes have no
   root-netns route for it, so replies sent there would loop.

4. **NodePort bug (earlier in the same saga).** The kernel WireGuard module
   installs the server-side peer `AllowedIPs` (`10.8.0.0/24` **and
   `192.168.1.0/24`**) as routes in the pod netns' main table. The
   `192.168.1.0/24 dev wg0` route then made *every* pod reply to a LAN
   address — including NodePort SYN-ACKs for `:30200`/`:30201` — go into
   the tunnel toward the phones, killing all LAN->pod traffic
   (`192.168.1.21:30201` 100% timeout; other pods unaffected).
   **Fix:** the wg-easy pod's `postStart` hook runs a 5s loop that deletes
   that one route (it reappears on every client-config change, so a loop,
   not a one-shot). The `10.8.0.0/24 dev wg0` route is left alone — it is
   required for the tunnel.

5. **MASQUARDE/NAT inside the pod netns.** The v15 app writes
   `/etc/wireguard/wg0.conf` and brings the interface up with `wg-quick`
   (then `wg syncconf`); the generated `PostUp` includes
   `iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUARADE`,
   but the container's `iptables` is the **nft backend**, which cannot add
   a `MASQUARDE` target ("Chain 'MASQUARDE' does not exist") — so that
   PostUp line fails. What works in practice: the app installs the same
   MASQUARDE rule in the **legacy** iptables table itself at startup
   (observed in every healthy pod, counters moving). One pod started with
   a broken app init (no `wg0.conf` at all, no NAT) and off-site LAN
   access was dead until the pod was recreated. **Fix:** the `postStart`
   loop maintains an nftables MASQUARDE rule (`ip nat masq_post`) as a
   guaranteed safety net — `nft` is the only in-container tool that can
   add it (the nft backend of `iptables` fails; the legacy backend can't
   load the target `.so`; the nft chain spec needs double quotes and
   `priority 100`, displayed as `srcnat`).

6. **New clients silently lose LAN access (recurred twice).** A client
   created without explicit per-client settings gets the app defaults:
   `AllowedIPs = 0.0.0.0/0` (full tunnel) and `DNS = 1.1.1.1, 8.8.8.8` —
   and the server-side peer `AllowedIPs` collapses to the client's `/32`.
   The *client-side* `AllowedIPs` is what routes the home LAN into the
   tunnel on the device; the server-side entry only filters incoming
   sources, so the tunnel can look healthy (pings to `10.8.0.1` work,
   packets even arrive at the server) while LAN traffic misbehaves and
   internal names never resolve (public DNS answers
   `sonarr.jesseisageek.com` with the Cloudflare edge, not `192.168.1.25`).
   **Fix (the one that stuck, September 2026):** set per-client
   `AllowedIPs = 10.8.0.0/24, 192.168.1.0/24` and
   `DNS = 192.168.1.23` in the UI, then re-scan the QR on the device.
   The app re-writes `wg0.conf` + `wg syncconf` on that change, which
   also resets any stale server-side peer state.

## Repo changes

`bootstrap/templates/addons/wg-easy/app/statefulset.yaml.j2` (rendered to
`kubernetes/apps/wg-easy/wg-easy/app/statefulset.yaml`): full-spec
strategic-merge patch of the HelmRelease-owned StatefulSet (Helm leaves no
`last-applied-configuration` baseline, so the patch must carry the complete
spec — selector, template, `podManagementPolicy`, etc. — or the empty-base
merge drops `spec.selector`). The only functional delta is the `postStart`
hook:

```sh
nohup sh -c 'while :; do
  ip route del 192.168.1.0/24 dev wg0 2>/dev/null
  nft add table ip nat 2>/dev/null
  nft list chain ip nat masq_post 2>/dev/null | grep -q masquerade || {
    nft delete chain ip nat masq_post 2>/dev/null
    nft add chain ip nat masq_post "{ type nat hook postrouting priority 100; policy accept; }" 2>/dev/null
    nft add rule ip nat masq_post ip saddr 10.8.0.0/24 oifname eth0 masquerade 2>/dev/null
  }
  sleep 5
done' >/dev/null 2>&1 &
```

App-level config (lives in the PVC `wg-easy` as `wg-easy.db`, not the
repo): global `host = vpn.jesseisageek.com`, port 30200; per-client
`DNS = 192.168.1.23`, `AllowedIPs = 10.8.0.0/24, 192.168.1.0/24` on the
JessePhone clients. `PersistentKeepalive` is 0 everywhere (the app
default): a client only re-keys when it sends something, so after a
server pod restart the tunnel stays dark until the phone next transmits
or the user toggles the VPN. Set a 25s keepalive per client if that
becomes a problem.

## Verifying

From the worker host, enter the pod netns (PID via
`/proc/<pid>/cgroup` containing `pod<UID>` — note cgroup v2 renders the UID
with underscores):

```sh
nsenter -t <PID> -n ip route                      # no 192.168.1.0/24 dev wg0
nsenter -t <PID> -n nft list table ip nat         # masq_post rule present
nsenter -t <PID> -n iptables-legacy -t nat -L POSTROUTING -v -n   # app's rule + counters
nsenter -t <PID> -n ping -c 2 10.8.0.2            # tunnel to a client
```

From a client (cellular, VPN on):

```
ping -c 5 10.8.0.1         # tunnel itself
ping -c 5 192.168.1.21     # node reply path
ping -c 5 <plex IP>        # third-party LAN reply path (needs router routes)
ssh <user>@<plex IP>
nslookup sonarr.jesseisageek.com    # must answer 192.168.1.25
```

## Gotchas

- **Client config changes require re-scanning** — the server-side DB change
  does not update installed clients. The v15 app stores clients in
  `/etc/wireguard/wg-easy.db` (SQLite, on the `wg-easy` PVC).
- **DDNS must track router reboots**, or the endpoint goes stale and the
  tunnel can't form until it updates.
- `plex.local` (mDNS) only resolves through k8s-gateway's mDNS reflection;
  it can never resolve via normal upstream DNS or on a phone that isn't
  using `192.168.1.23` as its tunnel DNS.
- **Pod restart kills the kernel-learned endpoints.** After any
  recreation of the wg-easy pod, server->client sends fail with
  "Destination Host Unreachable" until each client's next transmission
  (or VPN toggle) lets the kernel re-learn its endpoint. Client->server
  traffic and client->LAN traffic self-heal on demand; the app's
  60s cron only re-saves the config when a client or one-time link
  expires, so it does not flap endpoints on its own.
- The nft `masq_post` chain and the app's legacy rule can coexist
  harmlessly: after either one masquerades a packet, its source no longer
  matches `10.8.0.0/24`, so the other can't double-masquerade.
- The loop's `nft list ... | grep -q` guard makes the nft recreation
  no-churn: the chain is only rebuilt when the rule is absent.
- Diagnostic pattern for "which leg is dead": cumulative `iptables`/`nft`
  counters in the pod netns (arrivals per client IP via a throwaway
  `mangle` PREROUTING counter table) read before/after the client pings —
  arrivals prove the forward leg; the MASQUARDE counter proves the pod
  forwarded; node-side veth/ens18 stats prove node egress.

## The October 2026 incident — off-site `*.jesseisageek.com` (gitea/sonarr) unreachable

**Symptom (2026-10-27):** off-network (cellular, VPN on) the phone could not resolve or reach
`*.jesseisageek.com` — both internal-only names (`sonarr`, `home`) and public ones (`gitea`, `www`) —
while direct `192.168.1.*` IPs worked. On-network everything worked (VPN on or off). Three separate
causes, found in order:

### Cause 1 (client) — iCloud Private Relay hijacked the DNS
- The iPhone had iCloud **Private Relay** on. With relay active, iOS sends *all* DNS — including
  `*.jesseisageek.com` — to Apple's encrypted relay, bypassing the tunnel DNS (`192.168.1.23`).
  Apple's resolvers have no record of the internal-only names (`sonarr`/`home` → NXDOMAIN) and return
  Cloudflare public IPs for the public names, which don't serve the internal-only apps → timeout.
  Direct `192.168.1.*` kept working because Apple's relay deliberately does **not** relay RFC1918
  destinations — exactly the reported "IPs work, DNS doesn't" signature.
- **Proven by live capture** on the wg-easy pod netns: the phone bootstrapped `p27-fmip.icloud.com`
  over the tunnel, then ran QUIC/TLS sessions to Apple relay IPs (`17.248.x`/`17.250.x`/`17.253.x`)
  over the tunnel; **zero** `*.jesseisageek.com` queries reached `192.168.1.23`.
- **Fix (client):** Settings → [Apple ID] → iCloud → **Private Relay OFF** (and "Use Private Relay
  for all websites" off). After this the phone's DNS flowed to `192.168.1.23` correctly.

### Cause 2 (server) — Cilium BPF-LB `dsr` broke the VIP return path
- The cluster's load balancer ran Cilium `bpf-lb-mode: dsr` (direct-server-return, no SNAT;
  `bpf-lb-sock: false`). The gitea/sonarr VIPs are Cilium BPF-LB services: `192.168.1.24` =
  `network/nginx-external-controller`, `192.168.1.25` = `network/nginx-internal-controller`.
- WireGuard traffic is masqueraded in the wg-easy pod netns to the pod's k8s IP (`10.42.1.75`). In
  DSR the backend nginx pods reply **directly** to that pod-IP source instead of looping back through
  the LB; a reply to a pod-IP in another netns is never delivered back into the wg-easy pod → the
  phone's SYNs to `.24`/`.25:443` enter the tunnel but no SYN-ACK returns → timeout.
- **Why other paths worked:** plain LAN host IPs (e.g. Syncthing `192.168.1.211`) use normal routing
  (no BPF-LB DSR), and on-LAN clients hit the VIPs via the LAN return path — neither is affected by
  DSR.
- **Confirmed by self-test** from the wg-easy pod netns using the phone's exact post-masq source
  `10.42.1.75`: pre-fix `.24`/`.25` → timeout (no SYN-ACK); control `192.168.1.211` → instant; LAN
  source → works.
- **Fix (server, GitOps):** set the global Cilium LB mode to **SNAT** —
  `bootstrap_cilium_loadbalancer_mode: snat` in `bootstrap/vars/config.yaml`, rendered into the
  Cilium agent `helmvalues` (`bpf-lb-mode: snat`). With SNAT the LB rewrites the client source to the
  VIP, the backend replies to the VIP, and the LB un-SNATs + forwards the reply through the CNI back
  to the wg-easy pod → phone. A per-Service `service.cilium.io/load-balancer-mode: snat` annotation
  was tried first but is **inert on Cilium 1.16** (that version exposes only the global
  `bpf-lb-mode`, no per-service mode), so the global knob was the only fix available at the time.
  **Superseded 2026-11-24:** that global SNAT on Cilium 1.16.19 later blackholed *all* external-origin
  TCP to every BPF-LB frontend (see "The November 2026 incident"). Final state (post-incident,
  2026-11-24): Cilium 1.17.18 with global `dsr` restored and `bpf.lbModeAnnotation` **off** — the
  per-service annotation feature (which would keep .24/.25/.26 on `snat`) cannot run on 1.17.x with
  this cluster's native/veth datapath, because it forces `dsrDispatch=ipip`, which 1.17 only accepts
  with `--datapath-mode=lb-only` (the combo crashlooped the agents on both nodes, see below). The
  `service.cilium.io/forwarding-mode: snat` annotations therefore sit **inert** until the ≥1.18
  upgrade (datamodel mode); until then the phone→VIP masqueraded return-path quirk documented here
  recurs for direct phone→VIP flows, and the phone's supported paths are the wg-easy UI VIP `.26`
  (pod-netns path, works under dsr) and the full-tunnel profile. (Global `snat` — the alternative —
  reproduces the blackhole on 1.17.18 as well in this topology.)
- **Verified post-fix** (pod-netns self-test, src `10.42.1.75`, real SNI/vhosts): `gitea` via `.24` →
  200, `sonarr` via `.25` → 302, `home` via `.25` → 200. On-LAN unaffected (gitea 200 ~8 ms,
  sonarr 302 ~7 ms).
- **Tradeoff (as of October):** global SNAT added per-connection LB state and dropped DSR zero-copy
  for *all* BPF-LB services — negligible at home scale. That global-SNAT era ended 2026-11-24
  (see below); `01-architecture.md` / `03-configuration.md` / `06-networking.md` / `apps/kube-system.md`
  now record the final state (global `dsr`, `bpf.lbModeAnnotation` off on 1.17.x; "do not set the
  global mode back to `snat`, and do not re-enable `bpf.lbModeAnnotation` below Cilium 1.18") so a
  future change can't silently flip it without review.

### Cause 3 (client) — Safari's stale private-IP DNS answer
- After (1)+(2) the tunnel and server were fully working — proven by the pod-netns self-test **and**
  by the user's own **Firefox** test over the same VPN. Safari still timed out, and the capture showed
  Safari sending **zero** packets for gitea (no DNS query, no SYN): it was reusing a **stale
  DNS/cache answer** held from the Private-Relay era instead of re-querying `192.168.1.23`. Firefox
  re-resolves, so it worked. (Safari is an Apple system app and does **not** appear under
  Settings → Privacy → Local Network — that list is third-party apps only — so there is no toggle to
  flip.)
- **Resolution:** use **Firefox** for the home sites (verified working off-site), or to make Safari
  work: Settings → Safari → **Clear History and Website Data** + force-quit Safari (fallback:
  re-scan the wg-easy QR for a fresh profile).

### Supporting DNS change
- k8s-gateway: enabled **zone fallthrough** so *unknown* `*.jesseisageek.com` names resolve via
  upstream instead of NXDOMAIN — complements the split-DNS so the tunnel DNS answers public names
  correctly for off-LAN clients.

### Repo changes (this incident)
| Commit | Change |
|--------|--------|
| `784ba2f8` | k8s-gateway zone fallthrough (unknown `*.jesseisageek.com` → upstream) |
| `a784e925` | per-service `service.cilium.io/load-balancer-mode: snat` on nginx ext/internal — **inert on Cilium 1.16** (removed in `07c9046c`) |
| `9711121f` | **the fix**: `bootstrap_cilium_loadbalancer_mode: snat` (Cilium `bpf-lb-mode: snat`) + docs (01/03/06 + apps/kube-system) |
| `07c9046c` | removed the inert per-service annotations; single source of truth = global `bpf-lb-mode` |

> The many `*.sops.yaml` line changes in these commits are SOPS re-encryption churn, not real config
> changes.

### Client-side requirements (the iPhone)
1. iCloud **Private Relay OFF** (and "Use Private Relay for all websites" off).
2. Fresh wg-easy QR profile - `DNS = 192.168.1.23`, `AllowedIPs = 10.8.0.0/24, 192.168.1.0/24`;
   re-scan whenever the profile looks stale. Exception: **JessePhone3 (client id 6)
   deliberately runs full tunnel** (`AllowedIPs = 0.0.0.0/0, ::/0`, same DNS + keepalive 25)
   since 2026-11-24 - iOS did not apply the profile's split-DNS for public-looking names under
   split tunnel, so all its traffic now rides the tunnel (see the November incident).
3. Use **Firefox** for the home sites (or clear Safari's website data) - Safari can hold a stale
   private-IP answer that a reboot / cache-clear fixes.
4. The wg-easy UI is at `http://192.168.1.26/` (LB VIP; works off-site through the tunnel and
   on-LAN once the 2026-11-24 Cilium fix landed). The `:30201` NodePort works again too.

### Verifying off-site
In addition to the checks above: open `gitea.jesseisageek.com` and `sonarr.jesseisageek.com` in
**Firefox** on cellular + VPN → both load. Server-side self-test from the wg-easy pod netns
(src `10.42.1.75`): `https://gitea.jesseisageek.com` → 200, `sonarr` → 302.

## The November 2026 incident - JessePhone3 on full tunnel

**Symptom (2026-11-23/24, off-site LTE):** with the VPN on, `gitea.jesseisageek.com` /
`sonarr.jesseisageek.com` by *name* and external sites (1.1.1.1, example.com) hung, while
direct-IP home access worked. With the VPN off, gitea worked (public Cloudflare-fronted name)
and external sites worked. iCloud Private Relay was **ruled out** (the user's Apple ID has no
Private Relay option at all). All six stored client configs were verified correct in the DB
(split AllowedIPs + DNS 192.168.1.23); the server side measured clean end-to-end (tunnel
ingress/forward/masq, BPF-LB SNAT VIP returns, external egress from the phone's own tunnel
source 10.8.0.7).

**Root cause:** with the *split-tunnel* profile, iOS does not use the profile's DNS
(192.168.1.23) for public-looking names — a 10-minute instrumented watch on the k8s-gateway
showed **zero** DNS queries from the phone arriving at .23 even while the user tested by name.
Name-based sites therefore resolved via the phone's other resolver (public/cellular path), so
their fate tracked the phone's own external egress instead of the home network — and
`sonarr.jesseisageek.com` (no usable public record) was unreachable either way. Direct-IP
access needed no DNS and rode the (healthy) tunnel, which is why it alone kept working.

**Fix (server, 2026-11-24):** JessePhone3 (client id 6) flipped to **full tunnel** via the
wg-easy API: `AllowedIPs = 0.0.0.0/0, ::/0` (client- and server-side), DNS stays
`192.168.1.23`, keepalive 25. All names now resolve through the split-DNS gateway (gitea→.24,
sonarr→.25, public names→upstream) and all traffic rides the tunnel, whose egress was proven
working from the phone's source IP (`1.1.1.1` → 301, sonarr VIP .25 → 302). The user re-scans
the QR from the UI. App-wide defaults were already normalized (DNS .23, split AllowedIPs,
keepalive 25), so *new* clients still get the sane split-tunnel profile.

**Hardening:** the kernel installs a `default dev wg0` route for full-tunnel peers (AllowedIPs
0.0.0.0/0), which would compete with the pod's eth0 default and flap the pod's own egress
(UI/API :51821). The postStart hook now also deletes `default dev wg0` (v4 + v6) every 5s,
alongside the existing `192.168.1.0/24` removal. Client->external forwarding does not need the
wg0 default: such packets match the single eth0 default and get masqueraded; only return
traffic uses `10.8.0.0/24 dev wg0`.

> Operator note: mid-diagnosis a temporary `10.8.0.7/32` used for source-bound tests was
> briefly left on wg0 (a test-script abort skipped its cleanup line). That made the phone's IP
> a *local* address in the pod netns and blackholed all return traffic to the phone for ~9
> minutes — it looks exactly like "tunnel alive but IP access dead". Removed immediately on
> detection; the probe procedure now guarantees the cleanup runs in a separate step.

### Server-side: the external-TCP blackhole and the permanent fix (2026-11-24)

**Symptom:** on top of the client-side DNS problem above, *every* cluster UI was unreachable
over TCP from outside the cluster: workstation/LAN/WAN → `192.168.1.2x:30201` (wg-easy UI),
`:32500`, etc. all timed out, while the WireGuard tunnel (UDP 30200) and all in-cluster TCP
worked fine.

**Root cause:** the global `bpf-lb-mode: snat` set on 2026-10-27, running on Cilium
**1.16.19**, blackholed **all external-origin TCP to every BPF-LB frontend — NodePorts *and*
LoadBalancer VIPs — on both nodes**. Proven general with a brand-new service created during the
diagnosis (fresh VIP: external source times out, in-cluster source works; same signature as
every pre-existing frontend). The `cilium bpf lb ls` maps on both nodes are structurally
identical for the working-UDP and dead-TCP frontends, so the LB table is innocent — the drop
is in the TCP-specific ingress (from-netdev) handling under `snat` mode on 1.16.19 (BPF
monitor logged zero events for SYNs that NIC counters proved arrived). Cilium 1.16 has no
per-service forwarding mode, so no in-version workaround existed: either live with the
blackhole or revert to `dsr`, which would regress the October phone→VIP fix — hence the
Cilium version upgrade.

**Stopgap (2026-11-24):**
- New `wg-easy/wg-easy-ui-lb` — LoadBalancer VIP **`192.168.1.26`** → wg-easy `:51821`
  (ports 80 + 51821), folded into GitOps (`apps/wg-easy/wg-easy/app/lb-service.yaml`).
  Phone-through-tunnel traffic arrives in the wg-easy pod netns and is masqueraded to the pod
  IP — a path that works even under global snat — so with the full-tunnel profile the phone
  reaches the UI at `http://192.168.1.26/` immediately (verified end-to-end from the pod
  netns). Direct LAN/desktop access to it stayed broken until the upgrade.
- JessePhone3 (client id 6) runs the **full-tunnel** profile (`AllowedIPs = 0.0.0.0/0, ::/0`,
  DNS `192.168.1.23`, keepalive 25), so all of its traffic — home and external — rides the
  tunnel and egresses through the healthy pod netns.

**Permanent fix (2026-11-24):** Cilium **1.16.19 → 1.17.18** (flux chart *and* the k3s
bootstrap copy `custom-cilium-helmchart`; k8s 1.29 is e2e-tested on 1.17.x), plus:
- `bpf.lbModeAnnotation: true` (per-service forwarding mode — first available in 1.17);
- `loadBalancer.dsrDispatch: ipip` — mandatory on 1.17 with `lbModeAnnotation`: the
  agent refuses to start otherwise (`daemon/cmd/kube_proxy_replacement.go` asserts
  `--bpf-lb-dsr-dispatch=ipip`; the chart leaves it unset → "opt/geneve" → crashloop).
  With global `dsr` the IPIP dispatch is also the real cross-node DSR dispatch method.
- global `loadBalancer.mode` **back to `dsr`** — the hoped-for "1.17.18 accepts global `snat`"
  premise proved FALSE: under our topology (native routing + hostLegacyRouting) global `snat`
  reproduces the blackhole on 1.17.18 exactly (verified 2026-11-24: probe SYNs reach the node
  NIC, are dropped in the from-netdev BPF path with zero `cilium monitor` events, while
  in-cluster-origin traffic to the same NodePorts works fine). `datamodel` was tried first and
  is not a valid 1.17 mode value at all (a 1.18+ value; the agent aborts at startup with
  "Invalid value for --node-port-mode: datamodel"). Global `dsr` restores the pre-October
  external-origin TCP behavior for all NodePorts/VIPs;
- per-service annotation **`service.cilium.io/forwarding-mode: snat`** on exactly the
  services carrying the masqueraded phone→VIP flow that needs SNAT return paths:
  `nginx-external-controller` (.24), `nginx-internal-controller` (.25), `wg-easy-ui-lb` (.26);
- `bpf.masquerade: false` + `hostLegacyRouting: true` kept untouched (UDP checksum safety net).

Rollback = revert the commits (Flux returns to 1.16.19 global `snat` = the pre-fix state).

**Post-upgrade crashloop and final resolution (2026-11-24, later the same day).** The
combination above — `bpf.lbModeAnnotation: true` + `loadBalancer.dsrDispatch: ipip` + global
`dsr` — cannot start on this cluster. The "ipip is mandatory with the annotation flag" half is
true (`daemon/cmd/kube_proxy_replacement.go` refuses to start without it), but 1.17 has a second,
previously-missed validation: `dsrDispatch=ipip` is only accepted with
`--datapath-mode=lb-only` — and this cluster runs `routingMode: native` / veth datapath. So the
agent daemonset fatal-looped on **both nodes** at hive start ("DSR dispatch mode ipip only
supported for --datapath-mode=lb-only"); a follow-up attempt to dodge the blackhole by switching
the global mode to `snat` (keeping `dsrDispatch: ipip`) still left external-origin TCP to every
BPF-LB frontend blackholed (the topology-specific `snat` drop), so the domain stayed down.
While the agents were down, kube-proxy replacement died cluster-wide: inter-node pod traffic
broke (Longhorn engine↔replica dials timed out, gitea PostgreSQL PVCs served I/O errors → all
three postgres pods and the gitea app pod crashlooped), and the edge nginx 503'd
`gitea.jesseisageek.com` and everything else fronted through it.

**True root cause (established 2026-11-24): wg-quick full-tunnel policy routing in the pod netns — NOT Cilium.** The JessePhone3 profile (re-scanned Oct 2026) is full-tunnel (`AllowedIPs = 0.0.0.0/0, ::/0`). When wg-quick loads such a peer it installs `default dev wg0` into routing table **51820** plus the policy rules `not from all fwmark 0xca6c lookup 51820` (v4+v6) **in the pod's netns**. Those rules send ALL unmarked egress from the pod — its own connections *and* external traffic forwarded for VPN clients — into the tunnel: an external packet is encapsulated and sent back toward the phone that sent it, where it loops/black-holes. Symptom: "external websites hang, internal sites work" — LAN replies are unaffected because `192.168.1.0/24` lives in the main table, which the existing postStart hook already polices. The hook never touched table 51820 or the fwmark rules, so the bug lay dormant from the October re-scan until the **Nov 16 pod recreation (NAS disk failure)** booted a fresh netns that loaded the full-tunnel peer for the first time.

Exoneration of Cilium, concretely: the identical failure (every TCP connect from the netns `EHOSTUNREACH`; ICMP and sibling pods on the same node fine) reproduced on **both 1.17.18 and 1.16.19** and on **both nodes**, and disappeared in all four combinations by flushing table 51820 and deleting the two fwmark rules. The earlier `wg0` up/down bisection is also explained by this (with wg0 down, the hijacked routes simply have no exit). The claim that "1.17.x breaks TCP egress from pods with a second interface" is **retracted** — it was the full-tunnel table all along. (1.17.18 *cannot start* on this cluster with the configs we require — the ipip/datamodel validation crashloops above remain real — and the >=1.18 `datamodel` + per-service-`snat` project for the phone→VIP return path is unchanged.)

**Final state (2026-11-24):**
- postStart hook extended (statefulset.yaml + bootstrap template): every 5 s it also runs
  `ip -4/-6 route flush table 51820` and `ip -4/-6 rule del not from all fwmark 0xca6c lookup 51820` —
  the netns is now robust against any current or future full-tunnel client. Full-tunnel clients
  work correctly: their external traffic egresses via eth0 + MASQUERADE; split-tunnel clients
  are unaffected; legitimate return traffic arrives on wg0 and matches the `10.8.0.0/24` route.
- Cilium **rolled back to 1.16.19** (pre-October shape: global `dsr`, `bpf.lbModeAnnotation`
  off, no `bpf-lb-dsr-dispatch`, `masquerade: false` + `hostLegacyRouting: true`, pinned VIPs) —
  the exact state that ran clean from Aug/Sep through early Oct, and the safe default while
  1.17.x cannot start on this cluster. Accepted consequence (same as pre-October): direct
  phone→VIP masqueraded flows run DSR again; phones keep working via the full-tunnel profile
  and the wg-easy UI VIP `.26`.
- Worker `nodeSelector` pin added mid-investigation: **removed** (both nodes behave identically
  once the full-tunnel table is stripped).

**Verification (2026-11-24, pod netns, worker, 1.16.19, after removing the full-tunnel rules):**
`.20:6443` OK · k8s-gateway DNS `.23:53` OK · `1.1.1.1:443` OK · `example.com` resolves via
k8s-gateway upstream fallthrough and `HTTPS example.com` → **200** (identical pass on the
controller-node pod). Workstation-side matrix (`.20`/`.21` `:30201`, `http://.26/`, gitea/sonarr
domains) and the user's phone re-test: _pending user confirmation._

**Re-test checklist (user, phone):**
1. WireGuard app: import/re-scan the JessePhone3 profile (full-tunnel); VPN ON.
2. iCloud **Private Relay** OFF (where the option exists).
3. Open `http://192.168.1.26/` → the wg-easy UI loads.
4. An external site (e.g. cnn.com) loads, and `sonarr.jesseisageek.com` /
   `gitea.jesseisageek.com` load in **Firefox** (Safari can hold stale private-IP answers).

Desktops: `https://<app>.jesseisageek.com` (LAN) and direct `192.168.1.2x:30201`-style access
should work again from the LAN without any VPN.

## The 2026-11-25/26 incident — external sites dead over the VPN: the `.23` VIP vanished from the LAN

**Symptom:** off-site, VPN on: external websites hang; home-LAN/IP access works. Internal
*name*-based sites also fail to resolve (they only "work" via direct IP/mDNS).

**Root cause (proven with packet captures on both nodes):** the cluster-DNS VIP
`192.168.1.23` (the `k8s-gateway` LoadBalancer service, pinned via
`lbipam.cilium.io/...`) was **no longer answered by any node on the LAN**:
`ip neigh` on both hosts shows `FAILED` for `.23`, and `cilium monitor` on both nodes proved
the phone's DNS queries exit the wg-easy pod netns and the node kernel stack and then simply
never reach the worker (zero events, zero drops) — the packet dies at the **ARP hop**.
Nothing on the segment claimed `.23` (no LBIPAM host address, the L2 announcer had no valid
entry to publish).

Why the VIP went dark: Cilium **LBIPAM** had recorded the service at
**`192.168.1.0`** — the pool's *first* address (our pool block is `192.168.1.0/24` and
`allowFirstLastIPs` was not set) — instead of the pinned `.23`. The pin annotation in this
repo used the **legacy singular key `lbipam.cilium.io/ip`**, which the running
Cilium **1.16.19** build silently ignores: on any fresh allocation the pool hands out the
first free IP. The fresh allocation happened when the Cilium upgrade of 2026-09-10 migrated
the pool CRD (`spec.cidrs` → `spec.blocks`, generation bump ⇒ full re-allocation);
`.24`/`.25` kept their old statuses and survived. It stayed invisible while JessePhone3 ran a
split-tunnel profile (iOS resolves public names outside the tunnel), and bit once the phone
moved to **full tunnel** (Oct 2026 re-scan): *all* DNS now goes to `.23`, so every external
name failed to resolve while direct-IP home access kept working. The 2026-11-24
"server-side clean" verifications missed it because pod-netns probes to `.23` are
short-circuited by local Cilium BPF (LB DNAT to the backend pod) and **never traverse the
wire** — only traffic from real tunnel clients exercises the dead LAN path.

**Fix (2026-11-25/26):**
- Pinned annotation switched to the honored plural key **`lbipam.cilium.io/ips`** on all three
  VIP services (`k8s-gateway` `.23`, `nginx-external` `.24`, `nginx-internal` `.25`) — repo
  HelmReleases *and* bootstrap templates. Applied live first (`kubectl annotate`); the agent
  immediately released `.0` and satisfied the pin: `status.loadBalancer = 192.168.1.23`.
- Pool hardened with **`allowFirstLastIPs: No`** (`cilium-l2.yaml` + template) so a future
  failed/unpinned allocation can never silently take the subnet's network/broadcast address
  as a VIP again.
- Rolling `cilium` agent restarts (after each state correction) so agents re-import service
  status and the L2 announcer (lease holder: currently kube-worker) republishes the VIPs on
  the wire.

**Verified (2026-11-26):** `ip neigh` from the controller host resolves `.23` to the worker's
MAC (announcer answering ARP on the wire); DNS query for `example.com` to `192.168.1.23:53`
from the wg-easy pod netns — the *phone's exact path* (netns masq → node stack → LAN → BPF-LB
→ gateway pod → upstream) — returns real upstream answers.

**Second bug found the same night (pcap-proven) — node-SNAT made tunnel traffic look
inter-node, so the peer node skipped LoadBalancer DNAT:** with the `.23` VIP restored, the
phone's DNS *still* timed out. Synchronized captures on both nodes + inside the pod netns
showed the full chain up to the wire: netns masq (`10.8.0.7 → 10.42.0.162`) → **node stack
re-SNAT to `192.168.1.20`** (`CILIUM_POST_nat`: `ip saddr 10.42.0.0/24 … masquerade`) → wire
→ worker. On the worker, Cilium sees src = a k8s **node IP** and treats it as trusted
inter-node traffic: it does **no LB DNAT**, the kernel re-routes the packet (114 re-emitted
queries captured leaving the worker), and it dies at the router. Replies therefore never
existed. Non-node sources were fine all along — a `dig` from a plain LAN IP
(`-b 192.168.1.50`) to `.23` worked while the phone's identical query blackholed. Only
full-tunnel clients hit this: split-tunnel phones send public DNS over cellular, and direct
LAN-*IP* access never involves an LB VIP.

Earlier "server-side verified" checks had masked it twice: (a) pod-netns probes are
short-circuited by the local node's BPF LB and never cross the wire; (b) a socket bound to
`10.8.0.7` inside the netns exits with a **non-cluster** source, which the node does not
masquerade — so it exercised the working path, not the phone's.

**Fix (2026-11-26, commit `dd2d8cea`):** `bpfMasqueradeRange: 192.168.1.23/32 … .26/32` in
the Cilium values (repo + bootstrap template) — the four LBIPAM VIPs are excluded from
node-level masquerade, so tunnel traffic keeps its pod source IP on the wire. The peer
node's BPF LB then DNATs normally and returns the reply (src = VIP) to the pod IP → netns
un-masq → `wg0` → phone. Verified end-to-end with a pod-CIDR source test across the wire;
phone re-test by the user confirms.

> Lesson: for LB-IPAM VIPs, always verify **from off-LAN / through the tunnel** (or watch
> `ip neigh` + `cilium monitor` on both nodes). Pod-netns and in-cluster probes to a LoadBalancer
> VIP prove nothing about the LAN-facing path. And when simulating a tunnel client, the test
> source must be a **cluster-source that the node will masquerade** (pod-CIDR), or the test
> exits with a different source identity than the real flow and silently tests a different
> datapath. Node-SNAT'd (src = peer node IP) packets are exempt from LB DNAT on the peer
> node — keep LB VIPs out of `bpfMasqueradeRange`-style node re-SNAT.
