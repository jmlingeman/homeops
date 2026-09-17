# Off-site WireGuard VPN (wg-easy) — how it works and what was fixed

Status: **working** (verified off-site from a phone on cellular, September 2026).

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
